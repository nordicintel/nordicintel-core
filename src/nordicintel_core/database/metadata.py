"""Atomic, language-scoped metadata persistence."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from typing import Any

from psycopg.types.json import Jsonb

from nordicintel_core.errors import AdmissionError
from nordicintel_core.models import (
    Category,
    Dimension,
    LanguageState,
    NormalizedTableMetadata,
    deterministic_hash,
)

from ._typing import Connection
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

    def resolve_id(self, table_or_alias: str) -> str | None:
        row = self.connection.execute(
            read_query("dataset_resolve.sql"), (table_or_alias, table_or_alias)
        ).fetchone()
        return None if row is None else str(row["id"])

    def ensure_identity(
        self, provider_id: str, native_table_id: str, *, preferred_id: str | None = None
    ) -> str:
        existing = self.connection.execute(
            read_query("dataset_find_identity.sql"), (provider_id, native_table_id)
        ).fetchone()
        if existing is not None:
            return str(existing["id"])

        base = preferred_id or canonical_slug(provider_id, native_table_id)
        suffix = hashlib.sha256(f"{provider_id}\0{native_table_id}".encode()).hexdigest()[:10]
        for candidate in (base, f"{base}-{suffix}"):
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
            read_query("metadata_get.sql"), (table_id, language)
        ).fetchone()
        if row is None:
            return None
        category_rows = self.connection.execute(
            read_query("metadata_categories.sql"), (table_id, language)
        ).fetchall()
        by_dimension: dict[str, list[Category]] = {}
        for category_row in category_rows:
            dimension_code = str(category_row.pop("dimension_code"))
            by_dimension.setdefault(dimension_code, []).append(
                Category.model_validate(category_row)
            )
        dimensions: list[Dimension] = []
        roles: dict[str, list[str]] = {}
        for dimension_row in self.connection.execute(
            read_query("metadata_dimensions.sql"), (table_id, language)
        ).fetchall():
            role = dimension_row.get("role")
            if role is not None:
                roles.setdefault(str(role), []).append(str(dimension_row["code"]))
            dimension_row["categories"] = by_dimension.get(str(dimension_row["code"]), [])
            dimensions.append(Dimension.model_validate(dimension_row))
        aliases = [
            str(alias["alias"])
            for alias in self.connection.execute(
                read_query("metadata_aliases.sql"), (table_id,)
            ).fetchall()
        ]
        row["dimensions"] = dimensions
        row["roles"] = roles
        row["aliases"] = aliases
        return NormalizedTableMetadata.model_validate(row)

    def mark_checked(self, table_id: str, language: str) -> None:
        with self.connection.transaction():
            row = self.connection.execute(
                read_query("metadata_mark_checked.sql"),
                (table_id, language.strip().lower()),
            ).fetchone()
        if row is None:
            raise AdmissionError(404, "Table language does not exist")

    def upsert_language(self, metadata: NormalizedTableMetadata) -> str:
        """Replace one complete language representation and its marker atomically."""
        content_hash = deterministic_hash(
            metadata.model_dump(exclude={"comparison_marker", "aliases"}, mode="json")
        )
        with self.connection.transaction():
            table_id = self.ensure_identity(
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
                row = self.connection.execute(
                    read_query("dataset_alias_upsert.sql"),
                    (alias, table_id, "upstream", alias),
                ).fetchone()
                if row is None:
                    raise AdmissionError(409, f"Alias {alias!r} belongs to another table")
            self.connection.execute(
                read_query("metadata_update_search.sql"), (table_id, metadata.language)
            )
            self.connection.execute(read_query("dataset_mark_success.sql"), (table_id,))
        return table_id

    def record_failure(self, table_id: str, diagnostic: dict[str, Any]) -> None:
        with self.connection.transaction():
            row = self.connection.execute(
                read_query("dataset_mark_failure.sql"), (Jsonb(diagnostic), table_id)
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
        self, provider_id: str, seen_native_ids: Iterable[str], *, authoritative: bool
    ) -> list[str]:
        if not authoritative:
            raise ValueError("absence-based retirement requires authoritative discovery")
        seen = list(dict.fromkeys(seen_native_ids))
        with self.connection.transaction():
            rows = self.connection.execute(
                read_query("dataset_retire_unseen.sql"), (provider_id, seen)
            ).fetchall()
        return [str(row["id"]) for row in rows]
