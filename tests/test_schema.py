"""Guard the schema against drift.

The declarative model is the definition; the migration is what actually reaches a
database. These tests assert the two agree, and that the constraints Alembic's
autogenerate cannot reliably diff are really present.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import CheckConstraint, Connection, text
from sqlalchemy.orm import Session
from test_models import rich_metadata

from nordicintel_core.database import create_owner_engine
from nordicintel_core.database.migration_cli import _configuration
from nordicintel_core.database.schema import Base
from nordicintel_core.models import TableCatalogMetadata


def columns(table: str) -> set[str]:
    return {column.name for column in Base.metadata.tables[table].columns}


def test_definitions_cover_the_models() -> None:
    assert columns("table_metadata") == set(TableCatalogMetadata.model_fields) | {
        "table_id",
        "language",
        "dataset",
        "search_document",
    }
    assert set(Base.metadata.tables) == {
        "provider",
        "table_registry",
        "table_metadata",
        "table_language_state",
        "harvest_schedule",
        "harvest_job",
        "harvest_item",
    }
    assert "retired" in columns("table_registry")
    assert "discontinued" not in columns("table_registry")
    assert columns("harvest_item") == {
        "id",
        "job_id",
        "native_table_id",
        "table_id",
        "status",
        "started_at",
        "finished_at",
        "error",
    }


def test_every_check_constraint_is_named() -> None:
    """An unnamed check cannot be asserted in the database or matched across revisions."""
    unnamed = [
        (table.name, str(constraint.sqltext))
        for table in Base.metadata.tables.values()
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint) and constraint.name is None
    ]
    assert unnamed == []


def database_url() -> str:
    value = os.environ.get("NORDICINTEL_TEST_DATABASE_URL")
    if not value:
        pytest.skip("NORDICINTEL_TEST_DATABASE_URL is not configured")
    return value


@pytest.fixture
def migrated() -> Iterator[Connection]:
    """A database built the way deployment builds it: by running the migration.

    Everything happens inside one transaction that is always rolled back, so a shared
    test database is left exactly as it was found even though the schema is rebuilt.
    """
    engine = create_owner_engine(database_url())
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
            config = _configuration(database_url())
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
            yield connection
        finally:
            transaction.rollback()
    engine.dispose()


@pytest.mark.postgres
def test_migration_produces_exactly_the_declared_schema(migrated: Connection) -> None:
    """The drift guard: a migration that no longer builds the model fails here."""
    context = MigrationContext.configure(migrated)
    assert compare_metadata(context, Base.metadata) == []


@pytest.mark.postgres
def test_named_check_constraints_reach_the_database(migrated: Connection) -> None:
    """Autogenerate does not reliably diff CHECKs, so assert them against pg_constraint."""
    expected = {
        constraint.name
        for table in Base.metadata.tables.values()
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    actual = set(
        migrated.scalars(
            text(
                "SELECT conname FROM pg_constraint AS c "
                "JOIN pg_namespace AS n ON n.oid = c.connamespace "
                "WHERE c.contype = 'c' AND n.nspname = 'public'"
            )
        )
    )
    assert expected <= actual


@pytest.mark.postgres
def test_declared_indexes_reach_the_database(migrated: Connection) -> None:
    expected = {index.name for table in Base.metadata.tables.values() for index in table.indexes}
    actual = set(
        migrated.scalars(text("SELECT indexname FROM pg_indexes WHERE schemaname = 'public'"))
    )
    assert expected <= actual


@pytest.mark.postgres
def test_complete_metadata_storage(migrated: Connection) -> None:
    from nordicintel_core.database import HarvestRepository, MetadataRepository, ProviderRepository
    from nordicintel_core.models import HarvestRequest, ProviderDefinition

    session = Session(bind=migrated)
    ProviderRepository(session).upsert(
        ProviderDefinition(id="scb", label="SCB", adapter_type="pxweb")
    )
    queue = HarvestRepository(session)
    queue.enqueue("scb", HarvestRequest())
    job = queue.claim()
    assert job is not None
    metadata = rich_metadata()
    repository = MetadataRepository(session)
    table_id = repository.upsert_language(job.id, metadata)
    restored = repository.get_language(table_id, "sv")
    assert restored is not None
    assert restored.dataset.to_mapping() == metadata.metadata.dataset.to_mapping()
    assert restored.catalog == metadata.metadata.catalog
    assert (
        repository.load_language_state(table_id)["sv"].comparison_marker
        == metadata.comparison_marker
    )


@pytest.mark.postgres
def test_definition_downgrade_and_reupgrade(migrated: Connection) -> None:
    config = _configuration(database_url())
    config.attributes["connection"] = migrated
    command.downgrade(config, "base")
    assert not migrated.scalars(
        text(
            "SELECT tablename FROM pg_tables "
            "WHERE schemaname = 'public' AND tablename <> 'alembic_version'"
        )
    ).all()
    command.upgrade(config, "head")
    assert compare_metadata(MigrationContext.configure(migrated), Base.metadata) == []
