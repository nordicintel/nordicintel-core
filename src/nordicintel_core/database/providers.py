"""Provider persistence operations."""

from __future__ import annotations

from psycopg.types.json import Jsonb

from nordicintel_core.errors import AdmissionError
from nordicintel_core.models import ProviderDefinition

from ._typing import Connection, page
from .sql_files import read_query


class ProviderRepository:
    def __init__(self, connection: Connection) -> None:
        self.connection = connection

    def upsert(self, provider: ProviderDefinition) -> ProviderDefinition:
        with self.connection.transaction():
            row = self.connection.execute(
                read_query("provider_upsert.sql"),
                (
                    provider.id,
                    provider.label,
                    provider.description,
                    provider.website,
                    provider.region,
                    provider.adapter_type,
                    Jsonb(provider.config),
                    Jsonb(provider.secret_refs),
                    provider.enabled,
                ),
            ).fetchone()
        return ProviderDefinition.model_validate(row)

    def get(self, provider_id: str) -> ProviderDefinition | None:
        row = self.connection.execute(read_query("provider_get.sql"), (provider_id,)).fetchone()
        return None if row is None else ProviderDefinition.model_validate(row)

    def list(self, *, limit: int = 50, offset: int = 0) -> list[ProviderDefinition]:
        limit, offset = page(limit, offset)
        rows = self.connection.execute(read_query("provider_list.sql"), (limit, offset)).fetchall()
        return [ProviderDefinition.model_validate(row) for row in rows]

    def set_enabled(self, provider_id: str, enabled: bool) -> None:
        with self.connection.transaction():
            row = self.connection.execute(
                read_query("provider_set_enabled.sql"), (enabled, provider_id)
            ).fetchone()
        if row is None:
            raise AdmissionError(404, "Provider does not exist")
