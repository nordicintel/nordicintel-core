"""Atomic, language-scoped metadata persistence."""

from __future__ import annotations

import hashlib
import re
from typing import Any

from sqlalchemy import (
    ColumnElement,
    case,
    delete,
    exists,
    func,
    insert,
    literal,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import aggregate_order_by
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, selectinload

from nordicintel_core.errors import AdmissionError, OwnershipLost
from nordicintel_core.models import (
    Diagnostic,
    DiscoveryResult,
    LanguageState,
    NormalizedTableMetadata,
    TableSearchResult,
    deterministic_hash,
)

from ._typing import page
from .schema import Category, Dataset, DatasetAlias, DatasetMetadata, Dimension, Provider
from .schema import HarvestJob as JobRow

_SLUG_RUN = re.compile(r"[^a-z0-9._-]+")

# Held across a transaction while minting an identifier, so two workers cannot mint the
# same slug for different upstream tables. Distinct from the provider lock's salt.
_IDENTIFIER_LOCK_SALT = 1

# Identity lives on `dataset`; these four are the repository's own bookkeeping. Everything
# between them is one language's metadata, so the column list is derived rather than
# retyped: a model field with no column (or the reverse) fails the schema test instead of
# silently dropping data.
_IDENTITY_FIELDS = frozenset(
    {"provider_id", "table_id", "native_table_id", "aliases", "dimensions"}
)
_PERSISTENCE_COLUMNS = frozenset(
    {"dataset_id", "content_hash", "last_checked_at", "last_harvested_at", "search_document"}
)
_METADATA_COLUMNS = tuple(
    column.name
    for column in DatasetMetadata.__table__.columns
    if column.name not in _PERSISTENCE_COLUMNS
)
_DIMENSION_COLUMNS = tuple(
    column.name
    for column in Dimension.__table__.columns
    if column.name not in {"dataset_id", "language"}
)
_CATEGORY_COLUMNS = tuple(
    column.name
    for column in Category.__table__.columns
    if column.name not in {"dataset_id", "language", "dimension_code"}
)


def canonical_slug(provider_id: str, native_table_id: str) -> str:
    """Create the preferred readable slug used only when an identity is first minted."""
    native = _SLUG_RUN.sub("-", native_table_id.strip().lower()).strip("-._")
    if not native:
        native = hashlib.sha256(native_table_id.encode("utf-8")).hexdigest()[:12]
    return f"{provider_id}-{native}"


def _identifier_lock(candidate: str) -> ColumnElement[int]:
    return func.hashtextextended(candidate, _IDENTIFIER_LOCK_SALT)


def _published(include_discontinued: bool) -> ColumnElement[bool]:
    """Retired and publisher-discontinued tables are hidden together.

    They are distinct states — absence after an authoritative discovery versus a flag the
    publisher set — but neither is something a default search should surface.
    """
    if include_discontinued:
        return literal(True)
    return ~Dataset.retired & ~func.coalesce(DatasetMetadata.discontinued, False)


class MetadataRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _assert_owner(self, job_id: int, provider_id: str) -> None:
        """Refuse to write unless this backend still owns an uncancelled, enabled job."""
        owner = self.session.scalar(
            select(JobRow.provider_id)
            .join(Provider, Provider.id == JobRow.provider_id)
            .where(
                JobRow.id == job_id,
                JobRow.status == "running",
                JobRow.owner_backend_pid == func.pg_backend_pid(),
                ~JobRow.cancel_requested,
                Provider.enabled,
            )
        )
        if owner != provider_id:
            raise OwnershipLost("Job is not running on this connection or must stop")

    def resolve_id(self, table_or_alias: str) -> str | None:
        statement = (
            select(Dataset.id)
            .where(Dataset.id == table_or_alias)
            .union_all(
                select(DatasetAlias.dataset_id).where(
                    DatasetAlias.alias == table_or_alias,
                    DatasetAlias.valid_to.is_(None),
                )
            )
            .limit(1)
        )
        with self.session.begin():
            return self.session.scalar(statement)

    def _ensure_identity(
        self, provider_id: str, native_table_id: str, *, preferred_id: str | None = None
    ) -> str:
        """Mint a canonical slug once, or return the one this table already has.

        Slugs are never recomputed from a changed title, so the readable form is only a
        starting point; on collision the identity falls back to a deterministic suffix.
        """
        existing = self.session.scalar(
            select(Dataset.id).where(
                Dataset.provider_id == provider_id,
                Dataset.native_table_id == native_table_id,
            )
        )
        if existing is not None:
            return existing
        base = preferred_id or canonical_slug(provider_id, native_table_id)
        suffix = hashlib.sha256(f"{provider_id}\0{native_table_id}".encode()).hexdigest()[:10]
        for candidate in (base, f"{base}-{suffix}"):
            self.session.execute(select(func.pg_advisory_xact_lock(_identifier_lock(candidate))))
            minted = self.session.scalar(
                pg_insert(Dataset)
                .from_select(
                    ["id", "provider_id", "native_table_id"],
                    select(
                        literal(candidate), literal(provider_id), literal(native_table_id)
                    ).where(
                        ~exists(
                            select(literal(1))
                            .select_from(DatasetAlias)
                            .where(DatasetAlias.alias == candidate)
                        )
                    ),
                )
                .on_conflict_do_nothing()
                .returning(Dataset.id)
            )
            if minted is not None:
                return minted
            existing = self.session.scalar(
                select(Dataset.id).where(
                    Dataset.provider_id == provider_id,
                    Dataset.native_table_id == native_table_id,
                )
            )
            if existing is not None:
                return existing
        raise RuntimeError("Unable to mint a canonical table identity")

    def load_language_state(self, table_id: str) -> dict[str, LanguageState]:
        statement = (
            select(
                DatasetMetadata.language,
                DatasetMetadata.comparison_marker,
                DatasetMetadata.content_hash,
                DatasetMetadata.last_checked_at,
                DatasetMetadata.last_harvested_at,
                DatasetMetadata.language == func.any(Dataset.failed_languages),
            )
            .join(Dataset, Dataset.id == DatasetMetadata.dataset_id)
            .where(DatasetMetadata.dataset_id == table_id)
            .order_by(DatasetMetadata.language)
        )
        with self.session.begin():
            rows = self.session.execute(statement).all()
        return {
            row[0]: LanguageState(
                language=row[0],
                comparison_marker=row[1],
                content_hash=row[2],
                last_checked_at=row[3],
                last_harvested_at=row[4],
                failed=bool(row[5]),
            )
            for row in rows
        }

    def get_language(self, table_id: str, language: str) -> NormalizedTableMetadata | None:
        language = language.strip().lower()
        statement = (
            select(DatasetMetadata, Dataset.provider_id, Dataset.native_table_id)
            .join(Dataset, Dataset.id == DatasetMetadata.dataset_id)
            .where(DatasetMetadata.dataset_id == table_id, DatasetMetadata.language == language)
            .options(
                selectinload(DatasetMetadata.dimensions).selectinload(Dimension.categories)
            )
        )
        with self.session.begin():
            found = self.session.execute(statement).one_or_none()
            if found is None:
                return None
            row, provider_id, native_table_id = found
            aliases = list(
                self.session.scalars(
                    select(DatasetAlias.alias)
                    .where(
                        DatasetAlias.dataset_id == table_id,
                        DatasetAlias.valid_to.is_(None),
                    )
                    .order_by(DatasetAlias.alias)
                )
            )
            dimensions = [
                {
                    **{name: getattr(dimension, name) for name in _DIMENSION_COLUMNS},
                    "categories": [
                        {name: getattr(category, name) for name in _CATEGORY_COLUMNS}
                        for category in dimension.categories
                    ],
                }
                for dimension in row.dimensions
            ]
            return NormalizedTableMetadata.model_validate(
                {
                    **{name: getattr(row, name) for name in _METADATA_COLUMNS},
                    "provider_id": provider_id,
                    "table_id": table_id,
                    "native_table_id": native_table_id,
                    "aliases": aliases,
                    "dimensions": dimensions,
                }
            )

    def mark_checked(self, job_id: int, table_id: str, language: str) -> None:
        """Record that the catalogue was consulted without claiming a new metadata fetch."""
        with self.session.begin():
            provider_id = self.session.scalar(
                select(Dataset.provider_id).where(Dataset.id == table_id)
            )
            if provider_id is None:
                raise AdmissionError(404, "Table does not exist")
            self._assert_owner(job_id, provider_id)
            updated = self.session.scalar(
                update(DatasetMetadata)
                .where(
                    DatasetMetadata.dataset_id == table_id,
                    DatasetMetadata.language == language.strip().lower(),
                )
                .values(last_checked_at=func.now())
                .returning(DatasetMetadata.dataset_id)
            )
        if updated is None:
            raise AdmissionError(404, "Table language does not exist")

    def search(
        self,
        query: str,
        *,
        language: str | None = None,
        include_discontinued: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> list[TableSearchResult]:
        if not query.strip():
            raise ValueError("search query must not be blank")
        limit, offset = page(limit, offset)
        normalized_language = None if language is None else language.strip().lower()
        tsquery = func.websearch_to_tsquery("simple", query)
        rank = func.ts_rank(DatasetMetadata.search_document, tsquery).label("rank")
        statement = (
            select(
                Dataset.id,
                Dataset.provider_id,
                DatasetMetadata.language,
                DatasetMetadata.label,
                DatasetMetadata.description,
                func.coalesce(DatasetMetadata.discontinued, False).label("discontinued"),
                Dataset.operator_disabled,
                Dataset.availability_status,
                rank,
            )
            .join(DatasetMetadata, DatasetMetadata.dataset_id == Dataset.id)
            .where(
                DatasetMetadata.search_document.bool_op("@@")(tsquery),
                _published(include_discontinued),
                ~Dataset.operator_disabled,
                Dataset.availability_status == "available",
            )
            .order_by(rank.desc(), Dataset.id, DatasetMetadata.language)
            .limit(limit)
            .offset(offset)
        )
        if normalized_language is not None:
            statement = statement.where(DatasetMetadata.language == normalized_language)
        with self.session.begin():
            rows = self.session.execute(statement).all()
        return [
            TableSearchResult(
                table_id=row.id,
                provider_id=row.provider_id,
                language=row.language,
                label=row.label,
                description=row.description,
                discontinued=row.discontinued,
                operator_disabled=row.operator_disabled,
                availability_status=row.availability_status,
                rank=row.rank,
            )
            for row in rows
        ]

    def upsert_language(self, job_id: int, metadata: NormalizedTableMetadata) -> str:
        """Replace one complete language representation and its marker atomically.

        Metadata and its comparison marker are inseparable: the marker is only advanced in
        the same transaction that persisted what it describes.
        """
        content_hash = deterministic_hash(
            metadata.model_dump(exclude={"comparison_marker", "aliases"}, mode="json")
        )
        payload = metadata.model_dump(mode="json", exclude=set(_IDENTITY_FIELDS))
        with self.session.begin():
            self._assert_owner(job_id, metadata.provider_id)
            table_id = self._ensure_identity(
                metadata.provider_id,
                metadata.native_table_id,
                preferred_id=metadata.table_id,
            )
            values: dict[str, Any] = {
                **payload,
                "dataset_id": table_id,
                "content_hash": content_hash,
                "last_checked_at": func.now(),
                "last_harvested_at": func.now(),
            }
            self.session.execute(
                pg_insert(DatasetMetadata)
                .values(**values)
                .on_conflict_do_update(
                    index_elements=[DatasetMetadata.dataset_id, DatasetMetadata.language],
                    set_={
                        name: value
                        for name, value in values.items()
                        if name not in {"dataset_id", "language"}
                    },
                )
            )
            self._replace_dimensions(table_id, metadata)
            self._upsert_aliases(table_id, metadata.aliases)
            self._refresh_search_document(table_id, metadata.language)
            self._mark_success(table_id, metadata.language)
        return table_id

    def _replace_dimensions(self, table_id: str, metadata: NormalizedTableMetadata) -> None:
        """Rewrite this language's dimensions; categories cascade from the delete."""
        self.session.execute(
            delete(Dimension).where(
                Dimension.dataset_id == table_id,
                Dimension.language == metadata.language,
            )
        )
        for dimension in metadata.dimensions:
            dumped = dimension.model_dump(mode="json")
            self.session.execute(
                insert(Dimension).values(
                    dataset_id=table_id,
                    language=metadata.language,
                    **{name: dumped[name] for name in _DIMENSION_COLUMNS},
                )
            )
            for category in dimension.categories:
                dumped_category = category.model_dump(mode="json")
                self.session.execute(
                    insert(Category).values(
                        dataset_id=table_id,
                        language=metadata.language,
                        dimension_code=dimension.code,
                        **{name: dumped_category[name] for name in _CATEGORY_COLUMNS},
                    )
                )

    def _upsert_aliases(self, table_id: str, aliases: list[str]) -> None:
        for alias in aliases:
            self.session.execute(select(func.pg_advisory_xact_lock(_identifier_lock(alias))))
            claimed = self.session.scalar(
                pg_insert(DatasetAlias)
                .from_select(
                    ["alias", "dataset_id", "kind"],
                    select(literal(alias), literal(table_id), literal("upstream")).where(
                        # An alias may never shadow another table's canonical identifier.
                        ~exists(
                            select(literal(1))
                            .select_from(Dataset)
                            .where(Dataset.id == alias)
                        )
                    ),
                )
                .on_conflict_do_update(
                    index_elements=[DatasetAlias.alias],
                    set_={"dataset_id": table_id, "kind": "upstream", "valid_to": None},
                    where=DatasetAlias.dataset_id == table_id,
                )
                .returning(DatasetAlias.alias)
            )
            if claimed is None:
                raise AdmissionError(409, f"Alias {alias!r} belongs to another table")

    def _refresh_search_document(self, table_id: str, language: str) -> None:
        """Index labels with their metadata, so search never needs a second queue."""
        dimension_labels = (
            select(
                func.string_agg(
                    Dimension.label, aggregate_order_by(literal(" "), Dimension.index)
                )
            )
            .where(Dimension.dataset_id == table_id, Dimension.language == language)
            .scalar_subquery()
        )
        category_labels = (
            select(
                func.string_agg(
                    Category.label,
                    aggregate_order_by(literal(" "), Dimension.index, Category.index),
                )
            )
            .select_from(Category)
            .join(
                Dimension,
                (Dimension.dataset_id == Category.dataset_id)
                & (Dimension.language == Category.language)
                & (Dimension.code == Category.dimension_code),
            )
            .where(Category.dataset_id == table_id, Category.language == language)
            .scalar_subquery()
        )
        self.session.execute(
            update(DatasetMetadata)
            .where(
                DatasetMetadata.dataset_id == table_id,
                DatasetMetadata.language == language,
            )
            .values(
                search_document=func.to_tsvector(
                    "simple",
                    func.concat_ws(
                        " ",
                        DatasetMetadata.label,
                        DatasetMetadata.description,
                        DatasetMetadata.source,
                        dimension_labels,
                        category_labels,
                    ),
                )
            )
        )

    def _mark_success(self, table_id: str, language: str) -> None:
        """Clear only worker-owned failure state, and only for the language that succeeded.

        Operator fields are never named here, so a harvest cannot undo an operator's edit.
        """
        remaining = func.array_remove(Dataset.failed_languages, language)
        self.session.execute(
            update(Dataset)
            .where(Dataset.id == table_id)
            .values(
                availability_status=case(
                    (func.cardinality(remaining) == 0, "available"), else_="unavailable"
                ),
                failed_languages=remaining,
                last_error=case(
                    (func.cardinality(remaining) == 0, None), else_=Dataset.last_error
                ),
                last_harvested_at=func.now(),
                updated_at=func.now(),
            )
        )

    def record_failure(
        self,
        job_id: int,
        table_id: str,
        diagnostic: Diagnostic,
        *,
        language: str | None = None,
    ) -> None:
        """Record an upstream failure while keeping the last valid metadata in place."""
        if language is not None:
            language = language.strip().lower()
            if not language:
                raise ValueError("language must not be blank")
        with self.session.begin():
            provider_id = self.session.scalar(
                select(Dataset.provider_id).where(Dataset.id == table_id)
            )
            if provider_id is None:
                raise AdmissionError(404, "Table does not exist")
            self._assert_owner(job_id, provider_id)
            failed = (
                Dataset.failed_languages
                if language is None
                else case(
                    (
                        literal(language) == func.any(Dataset.failed_languages),
                        Dataset.failed_languages,
                    ),
                    else_=func.array_append(Dataset.failed_languages, language),
                )
            )
            self.session.execute(
                update(Dataset)
                .where(Dataset.id == table_id)
                .values(
                    availability_status="unavailable",
                    failed_languages=failed,
                    last_error=diagnostic.model_dump(mode="json"),
                    updated_at=func.now(),
                )
            )

    def set_operator_disabled(self, table_id: str, disabled: bool) -> None:
        """Change the operator field only; worker-owned availability is untouched."""
        with self.session.begin():
            updated = self.session.scalar(
                update(Dataset)
                .where(Dataset.id == table_id)
                .values(operator_disabled=disabled, updated_at=func.now())
                .returning(Dataset.id)
            )
        if updated is None:
            raise AdmissionError(404, "Table does not exist")

    def retire_unseen(
        self, job_id: int, provider_id: str, discovery: DiscoveryResult
    ) -> list[str]:
        """Retire tables absent from a complete inventory. Never call it after a partial one."""
        if not discovery.authoritative or discovery.scope.table_id is not None:
            raise ValueError("absence-based retirement requires authoritative discovery")
        seen = [entry.source_table_id for entry in discovery.entries]
        with self.session.begin():
            self._assert_owner(job_id, provider_id)
            return list(
                self.session.scalars(
                    update(Dataset)
                    .where(
                        Dataset.provider_id == provider_id,
                        ~Dataset.native_table_id.in_(seen),
                    )
                    .values(retired=True, updated_at=func.now())
                    .returning(Dataset.id)
                )
            )
