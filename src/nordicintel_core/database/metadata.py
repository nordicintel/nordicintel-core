"""Atomic acceptance of catalog metadata and JSON-stat language Datasets."""

from __future__ import annotations

import hashlib
import re

from sqlalchemy import ColumnElement, case, func, literal, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from nordicintel_core.errors import AdmissionError, OwnershipLost
from nordicintel_core.models import (
    AvailabilityStatus,
    Diagnostic,
    DiscoveryResult,
    LanguageState,
    MetadataFetchResult,
    ServingMode,
    TableCatalogMetadata,
    TableLanguageMetadata,
    TableSearchResult,
    deterministic_hash,
)
from nordicintel_core.models import TableRecord as TableModel

from ._typing import page
from .schema import HarvestJob as JobRow
from .schema import Provider, TableLanguageState, TableMetadata, TableRecord

_SLUG_RUN = re.compile(r"[^a-z0-9._-]+")
_CATALOG_COLUMNS = tuple(TableCatalogMetadata.model_fields)


def canonical_slug(provider_id: str, native_table_id: str) -> str:
    """Mint the readable identity once; titles never participate."""
    native = _SLUG_RUN.sub("-", native_table_id.strip().lower()).strip("-._")
    if not native:
        native = hashlib.sha256(native_table_id.encode("utf-8")).hexdigest()[:12]
    return f"{provider_id}-{native}"


def _published(include_discontinued: bool) -> ColumnElement[bool]:
    if include_discontinued:
        return literal(True)
    return ~TableRecord.retired & ~func.coalesce(TableMetadata.discontinued, False)


class MetadataRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _assert_owner(self, job_id: int, provider_id: str) -> None:
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

    def resolve_id(self, table_id: str) -> str | None:
        """Resolve only a canonical Table identifier."""
        with self.session.begin():
            return self.session.scalar(select(TableRecord.id).where(TableRecord.id == table_id))

    def get_table(self, table_id: str) -> TableModel | None:
        """Resolve native routing identity and controls independently of a language."""
        with self.session.begin():
            row = self.session.scalar(select(TableRecord).where(TableRecord.id == table_id))
            if row is None:
                return None
            return TableModel(
                table_id=row.id,
                provider_id=row.provider_id,
                native_table_id=row.native_table_id,
                serving_mode=ServingMode(row.serving_mode),
                retired=row.retired,
                operator_disabled=row.operator_disabled,
                availability_status=AvailabilityStatus(row.availability_status),
            )

    def _ensure_identity(self, provider_id: str, native_table_id: str) -> str:
        existing = self.session.scalar(
            select(TableRecord.id).where(
                TableRecord.provider_id == provider_id,
                TableRecord.native_table_id == native_table_id,
            )
        )
        if existing is not None:
            return existing
        base = canonical_slug(provider_id, native_table_id)
        suffix = hashlib.sha256(f"{provider_id}\0{native_table_id}".encode()).hexdigest()[:10]
        for candidate in (base, f"{base}-{suffix}"):
            minted = self.session.scalar(
                pg_insert(TableRecord)
                .values(
                    id=candidate,
                    provider_id=provider_id,
                    native_table_id=native_table_id,
                )
                .on_conflict_do_nothing()
                .returning(TableRecord.id)
            )
            if minted is not None:
                return minted
            existing = self.session.scalar(
                select(TableRecord.id).where(
                    TableRecord.provider_id == provider_id,
                    TableRecord.native_table_id == native_table_id,
                )
            )
            if existing is not None:
                return existing
        raise RuntimeError("Unable to mint a canonical table identity")

    def load_language_state(self, table_id: str) -> dict[str, LanguageState]:
        with self.session.begin():
            rows = self.session.scalars(
                select(TableLanguageState)
                .where(
                    TableLanguageState.table_id == table_id,
                )
                .order_by(TableLanguageState.language)
            ).all()
            return {
                row.language: LanguageState(
                    language=row.language,
                    comparison_marker=row.comparison_marker,
                    content_hash=row.content_hash,
                    last_checked_at=row.last_checked_at,
                    last_harvested_at=row.last_harvested_at,
                    failed=row.last_error is not None,
                    last_error=row.last_error,
                )
                for row in rows
            }

    def get_language(self, table_id: str, language: str) -> TableLanguageMetadata | None:
        # One row/query carries the entire Dataset, so readers cannot mix revisions.
        with self.session.begin():
            row = self.session.scalar(
                select(TableMetadata).where(
                    TableMetadata.table_id == table_id,
                    TableMetadata.language == language.strip().lower(),
                )
            )
            if row is None:
                return None
            return TableLanguageMetadata.model_validate(
                {
                    "table_id": table_id,
                    "language": row.language,
                    "catalog": {name: getattr(row, name) for name in _CATALOG_COLUMNS},
                    "dataset": row.dataset,
                }
            )

    def mark_checked(self, job_id: int, table_id: str, language: str) -> None:
        with self.session.begin():
            provider_id = self.session.scalar(
                select(TableRecord.provider_id).where(TableRecord.id == table_id)
            )
            if provider_id is None:
                raise AdmissionError(404, "Table does not exist")
            self._assert_owner(job_id, provider_id)
            updated = self.session.scalar(
                update(TableLanguageState)
                .where(
                    TableLanguageState.table_id == table_id,
                    TableLanguageState.language == language.strip().lower(),
                )
                .values(last_checked_at=func.now())
                .returning(TableLanguageState.table_id)
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
        tsquery = func.websearch_to_tsquery("simple", query)
        rank = func.ts_rank(TableMetadata.search_document, tsquery).label("rank")
        statement = (
            select(
                TableRecord.id,
                TableRecord.provider_id,
                TableMetadata.language,
                TableMetadata.label,
                TableMetadata.description,
                func.coalesce(TableMetadata.discontinued, False).label("discontinued"),
                TableRecord.operator_disabled,
                TableRecord.availability_status,
                rank,
            )
            .join(TableMetadata, TableMetadata.table_id == TableRecord.id)
            .join(Provider, Provider.id == TableRecord.provider_id)
            .where(
                TableMetadata.search_document.bool_op("@@")(tsquery),
                _published(include_discontinued),
                ~TableRecord.operator_disabled,
                TableRecord.availability_status == "available",
                Provider.enabled,
            )
            .order_by(rank.desc(), TableRecord.id, TableMetadata.language)
            .limit(limit)
            .offset(offset)
        )
        if language is not None:
            statement = statement.where(TableMetadata.language == language.strip().lower())
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
                    availability_status=AvailabilityStatus(row.availability_status),
                    rank=row.rank,
                )
                for row in rows
            ]

    def upsert_language(self, job_id: int, result: MetadataFetchResult) -> str:
        """Accept the Dataset, catalog, search projection and marker together."""
        # Revalidate even objects constructed via model_copy/model_construct before writes.
        result = MetadataFetchResult.model_validate(result.model_dump())
        metadata = result.metadata
        content_hash = deterministic_hash(metadata.model_dump())
        catalog = metadata.catalog.model_dump(mode="json")
        terms = [
            metadata.catalog.label,
            metadata.catalog.description,
            metadata.catalog.source,
            metadata.dataset.label,
            metadata.dataset.source,
            *(metadata.catalog.tags or []),
        ]
        for dimension in metadata.dataset.dimension.values():
            terms.append(dimension.label)
            terms.extend((dimension.category.label or {}).values())
        search_text = " ".join(term for term in terms if term)
        with self.session.begin():
            self._assert_owner(job_id, result.provider_id)
            table_id = self._ensure_identity(result.provider_id, result.native_table_id)
            values = {
                **catalog,
                "table_id": table_id,
                "language": metadata.language,
                "dataset": metadata.dataset.to_mapping(),
                "search_document": func.to_tsvector("simple", search_text),
            }
            self.session.execute(
                pg_insert(TableMetadata)
                .values(**values)
                .on_conflict_do_update(
                    index_elements=[TableMetadata.table_id, TableMetadata.language],
                    set_={
                        name: value
                        for name, value in values.items()
                        if name not in {"table_id", "language"}
                    },
                )
            )
            state = {
                "comparison_marker": result.comparison_marker,
                "content_hash": content_hash,
                "last_checked_at": func.now(),
                "last_harvested_at": func.now(),
                "last_error": None,
            }
            self.session.execute(
                pg_insert(TableLanguageState)
                .values(
                    table_id=table_id,
                    language=metadata.language,
                    **state,
                )
                .on_conflict_do_update(
                    index_elements=[TableLanguageState.table_id, TableLanguageState.language],
                    set_=state,
                )
            )
            self._mark_success(table_id, metadata.language)
        return table_id

    def _mark_success(self, table_id: str, language: str) -> None:
        """Clear only worker-owned failure state, and only for the language that succeeded.

        Operator fields are never named here, so a harvest cannot undo an operator's edit.
        """
        remaining = func.array_remove(TableRecord.failed_languages, language)
        self.session.execute(
            update(TableRecord)
            .where(TableRecord.id == table_id)
            .values(
                availability_status=case(
                    (func.cardinality(remaining) == 0, "available"), else_="unavailable"
                ),
                failed_languages=remaining,
                last_error=case(
                    (func.cardinality(remaining) == 0, None), else_=TableRecord.last_error
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
                select(TableRecord.provider_id).where(TableRecord.id == table_id)
            )
            if provider_id is None:
                raise AdmissionError(404, "Table does not exist")
            self._assert_owner(job_id, provider_id)
            failed = (
                TableRecord.failed_languages
                if language is None
                else case(
                    (
                        literal(language) == func.any(TableRecord.failed_languages),
                        TableRecord.failed_languages,
                    ),
                    else_=func.array_append(TableRecord.failed_languages, language),
                )
            )
            if language is not None:
                self.session.execute(
                    pg_insert(TableLanguageState)
                    .values(
                        table_id=table_id,
                        language=language,
                        last_error=diagnostic.model_dump(mode="json"),
                    )
                    .on_conflict_do_update(
                        index_elements=[TableLanguageState.table_id, TableLanguageState.language],
                        set_={"last_error": diagnostic.model_dump(mode="json")},
                    )
                )
            self.session.execute(
                update(TableRecord)
                .where(TableRecord.id == table_id)
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
                update(TableRecord)
                .where(TableRecord.id == table_id)
                .values(operator_disabled=disabled, updated_at=func.now())
                .returning(TableRecord.id)
            )
        if updated is None:
            raise AdmissionError(404, "Table does not exist")

    def retire_unseen(self, job_id: int, provider_id: str, discovery: DiscoveryResult) -> list[str]:
        """Retire tables absent from a complete inventory. Never call it after a partial one."""
        if not discovery.authoritative or discovery.scope.table_id is not None:
            raise ValueError("absence-based retirement requires authoritative discovery")
        seen = [entry.native_table_id for entry in discovery.entries]
        with self.session.begin():
            self._assert_owner(job_id, provider_id)
            return list(
                self.session.scalars(
                    update(TableRecord)
                    .where(
                        TableRecord.provider_id == provider_id,
                        ~TableRecord.native_table_id.in_(seen),
                    )
                    .values(retired=True, updated_at=func.now())
                    .returning(TableRecord.id)
                )
            )
