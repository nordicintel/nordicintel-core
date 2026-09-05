"""Atomic, language-scoped metadata persistence."""

from __future__ import annotations

import hashlib
import re

from psycopg.types.json import Jsonb

from nordicintel_core.errors import AdmissionError, OwnershipLost
from nordicintel_core.models import (
    Diagnostic,
    DiscoveryResult,
    LanguageState,
    NormalizedTableMetadata,
    TableSearchResult,
    deterministic_hash,
)

from ._typing import Connection, page
from .sql_files import read_query

_SLUG_RUN = re.compile(r"[^a-z0-9._-]+")


def canonical_slug(provider_id: str, native_table_id: str) -> str:
    """Create the preferred readable slug used only when an identity is first minted."""
    native = _SLUG_RUN.sub("-", native_table_id.strip().lower()).strip("-._")
    if not native:
        native = hashlib.sha256(native_table_id.encode("utf-8")).hexdigest()[:12]
    return f"{provider_id}-{native}"


class MetadataRepository:
    def __init__(self, connection: Connection) -> None:
        self.connection = connection

    def _assert_owner(self, job_id: int, provider_id: str) -> None:
        row = self.connection.execute(
            read_query("job_assert_owner.sql"), (job_id,)
        ).fetchone()
        if row is None or row["provider_id"] != provider_id:
            raise OwnershipLost("Job is not running on this connection or must stop")

    def resolve_id(self, table_or_alias: str) -> str | None:
        row = self.connection.execute(
            read_query("dataset_resolve.sql"), (table_or_alias, table_or_alias)
        ).fetchone()
        return None if row is None else str(row["id"])

    def _ensure_identity(
        self, provider_id: str, native_table_id: str, *, preferred_id: str | None = None
    ) -> str:
        with self.connection.transaction():
            existing = self.connection.execute(
                read_query("dataset_find_identity.sql"), (provider_id, native_table_id)
            ).fetchone()
            if existing is not None:
                return str(existing["id"])
            base = preferred_id or canonical_slug(provider_id, native_table_id)
            suffix = hashlib.sha256(
                f"{provider_id}\0{native_table_id}".encode()
            ).hexdigest()[:10]
            for candidate in (base, f"{base}-{suffix}"):
                self.connection.execute(read_query("identifier_lock.sql"), (candidate,))
                row = self.connection.execute(
                    read_query("dataset_insert_identity.sql"),
                    (candidate, provider_id, native_table_id, candidate),
                ).fetchone()
                if row is not None:
                    return str(row["id"])
                existing = self.connection.execute(
                    read_query("dataset_find_identity.sql"), (provider_id, native_table_id)
                ).fetchone()
                if existing is not None:
                    return str(existing["id"])
        raise RuntimeError("Unable to mint a canonical table identity")

    def load_language_state(self, table_id: str) -> dict[str, LanguageState]:
        rows = self.connection.execute(read_query("metadata_state.sql"), (table_id,)).fetchall()
        return {row["language"]: LanguageState.model_validate(row) for row in rows}

    def get_language(self, table_id: str, language: str) -> NormalizedTableMetadata | None:
        language = language.strip().lower()
        row = self.connection.execute(
            read_query("metadata_get_full.sql"), (table_id, language)
        ).fetchone()
        if row is None:
            return None
        roles: dict[str, list[str]] = {}
        for dimension in row["dimensions"]:
            role = dimension.get("role")
            if role is not None:
                roles.setdefault(str(role), []).append(str(dimension["code"]))
        row["roles"] = roles
        return NormalizedTableMetadata.model_validate(row)

    def mark_checked(self, job_id: int, table_id: str, language: str) -> None:
        with self.connection.transaction():
            provider = self.connection.execute(
                read_query("dataset_provider.sql"), (table_id,)
            ).fetchone()
            if provider is None:
                raise AdmissionError(404, "Table does not exist")
            self._assert_owner(job_id, str(provider["provider_id"]))
            row = self.connection.execute(
                read_query("metadata_mark_checked.sql"),
                (table_id, language.strip().lower()),
            ).fetchone()
        if row is None:
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
        rows = self.connection.execute(
            read_query("metadata_search.sql"),
            (
                query,
                query,
                normalized_language,
                normalized_language,
                include_discontinued,
                limit,
                offset,
            ),
        ).fetchall()
        return [TableSearchResult.model_validate(row) for row in rows]

    def upsert_language(self, job_id: int, metadata: NormalizedTableMetadata) -> str:
        """Replace one complete language representation and its marker atomically."""
        content_hash = deterministic_hash(
            metadata.model_dump(exclude={"comparison_marker", "aliases"}, mode="json")
        )
        with self.connection.transaction():
            self._assert_owner(job_id, metadata.provider_id)
            table_id = self._ensure_identity(
                metadata.provider_id,
                metadata.native_table_id,
                preferred_id=metadata.table_id,
            )
            self.connection.execute(
                read_query("metadata_upsert.sql"),
                (
                    table_id,
                    metadata.language,
                    metadata.label,
                    metadata.description,
                    Jsonb(metadata.notes),
                    metadata.source,
                    metadata.start_period,
                    metadata.end_period,
                    metadata.upstream_url,
                    Jsonb(metadata.comparison_marker)
                    if metadata.comparison_marker is not None
                    else None,
                    content_hash,
                ),
            )
            self.connection.execute(
                read_query("metadata_delete_dimensions.sql"),
                (table_id, metadata.language),
            )
            for dimension in metadata.dimensions:
                roles = [role for role, codes in metadata.roles.items() if dimension.code in codes]
                role = roles[0] if roles else dimension.role
                self.connection.execute(
                    read_query("metadata_insert_dimension.sql"),
                    (
                        table_id,
                        metadata.language,
                        dimension.code,
                        dimension.label,
                        dimension.ordinal,
                        role,
                        dimension.note,
                    ),
                )
                for category in dimension.categories:
                    self.connection.execute(
                        read_query("metadata_insert_category.sql"),
                        (
                            table_id,
                            metadata.language,
                            dimension.code,
                            category.code,
                            category.label,
                            category.ordinal,
                            category.note,
                            Jsonb(category.unit) if category.unit is not None else None,
                        ),
                    )
            for alias in metadata.aliases:
                self.connection.execute(read_query("identifier_lock.sql"), (alias,))
                row = self.connection.execute(
                    read_query("dataset_alias_upsert.sql"),
                    (alias, table_id, "upstream", alias),
                ).fetchone()
                if row is None:
                    raise AdmissionError(409, f"Alias {alias!r} belongs to another table")
            self.connection.execute(
                read_query("metadata_update_search.sql"), (table_id, metadata.language)
            )
            self.connection.execute(
                read_query("dataset_mark_success.sql"),
                (metadata.language, metadata.language, metadata.language, table_id),
            )
        return table_id

    def record_failure(
        self,
        job_id: int,
        table_id: str,
        diagnostic: Diagnostic,
        *,
        language: str | None = None,
    ) -> None:
        if language is not None:
            language = language.strip().lower()
            if not language:
                raise ValueError("language must not be blank")
        with self.connection.transaction():
            provider = self.connection.execute(
                read_query("dataset_provider.sql"), (table_id,)
            ).fetchone()
            if provider is None:
                raise AdmissionError(404, "Table does not exist")
            self._assert_owner(job_id, str(provider["provider_id"]))
            row = self.connection.execute(
                read_query("dataset_mark_failure.sql"),
                (
                    language,
                    language,
                    language,
                    Jsonb(diagnostic.model_dump(mode="json")),
                    table_id,
                ),
            ).fetchone()
        if row is None:
            raise AdmissionError(404, "Table does not exist")

    def set_operator_disabled(self, table_id: str, disabled: bool) -> None:
        with self.connection.transaction():
            row = self.connection.execute(
                read_query("dataset_set_operator_disabled.sql"), (disabled, table_id)
            ).fetchone()
        if row is None:
            raise AdmissionError(404, "Table does not exist")

    def retire_unseen(
        self, job_id: int, provider_id: str, discovery: DiscoveryResult
    ) -> list[str]:
        if not discovery.authoritative or discovery.scope.table_id is not None:
            raise ValueError("absence-based retirement requires authoritative discovery")
        seen = [entry.source_table_id for entry in discovery.entries]
        with self.connection.transaction():
            self._assert_owner(job_id, provider_id)
            rows = self.connection.execute(
                read_query("dataset_retire_unseen.sql"), (provider_id, seen)
            ).fetchall()
        return [str(row["id"]) for row in rows]
