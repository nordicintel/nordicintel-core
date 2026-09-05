"""Provider persistence operations."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from nordicintel_core.errors import AdmissionError
from nordicintel_core.models import ProviderDefinition

from ._typing import page
from .schema import Provider


def _definition(provider: Provider) -> ProviderDefinition:
    """Project the row explicitly; operational timestamps are not part of the contract."""
    return ProviderDefinition(
        id=provider.id,
        label=provider.label,
        description=provider.description,
        website=provider.website,
        region=provider.region,
        adapter_type=provider.adapter_type,
        config=provider.config,
        secret_refs=provider.secret_refs,
        enabled=provider.enabled,
    )


class ProviderRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert(self, provider: ProviderDefinition) -> ProviderDefinition:
        values = provider.model_dump()
        statement = (
            insert(Provider)
            .values(**values)
            .on_conflict_do_update(
                index_elements=[Provider.id],
                set_={
                    **{name: value for name, value in values.items() if name != "id"},
                    "updated_at": func.now(),
                },
            )
            .returning(Provider)
        )
        with self.session.begin():
            return _definition(self.session.scalars(statement).one())

    def get(self, provider_id: str) -> ProviderDefinition | None:
        with self.session.begin():
            entity = self.session.get(Provider, provider_id)
            return None if entity is None else _definition(entity)

    def list(self, *, limit: int = 50, offset: int = 0) -> list[ProviderDefinition]:
        limit, offset = page(limit, offset)
        statement = select(Provider).order_by(Provider.id).limit(limit).offset(offset)
        with self.session.begin():
            return [_definition(entity) for entity in self.session.scalars(statement)]

    def set_enabled(self, provider_id: str, enabled: bool) -> None:
        with self.session.begin():
            entity = self.session.get(Provider, provider_id)
            if entity is None:
                raise AdmissionError(404, "Provider does not exist")
            entity.enabled = enabled
            entity.updated_at = func.now()
