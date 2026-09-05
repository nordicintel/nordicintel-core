"""Guard the schema against drift.

The declarative model is the definition; the migration is what actually reaches a
database. These tests assert the two agree, and that the constraints Alembic's
autogenerate cannot reliably diff are really present.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import CheckConstraint, Connection, text
from sqlalchemy.orm import Session
from test_models import rich_metadata

from nordicintel_core.database import create_owner_engine
from nordicintel_core.database.migration_cli import _configuration
from nordicintel_core.database.schema import (
    Base,
    Category,
    DatasetMetadata,
    Dimension,
)
from nordicintel_core.models import Category as CategoryModel
from nordicintel_core.models import Dimension as DimensionModel
from nordicintel_core.models import NormalizedTableMetadata

IDENTITY_FIELDS = {"provider_id", "table_id", "native_table_id", "aliases", "dimensions"}
PERSISTENCE_COLUMNS = {
    "dataset_id",
    "content_hash",
    "last_checked_at",
    "last_harvested_at",
    "search_document",
}


def columns(table: str) -> set[str]:
    return {column.name for column in Base.metadata.tables[table].columns}


def test_definitions_cover_the_models() -> None:
    """Every model field has a column and every column has a field, with no database."""
    assert (
        columns("dataset_metadata")
        == (set(NormalizedTableMetadata.model_fields) - IDENTITY_FIELDS) | PERSISTENCE_COLUMNS
    )
    assert columns("dimension") == (set(DimensionModel.model_fields) - {"categories"}) | {
        "dataset_id",
        "language",
    }
    assert columns("category") == set(CategoryModel.model_fields) | {
        "dataset_id",
        "language",
        "dimension_code",
    }
    assert "retired" in columns("dataset")
    assert "discontinued" not in columns("dataset")
    assert not {"value", "status", "size", "ordinal"} & columns("dataset_metadata")


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
    expected = {
        index.name for table in Base.metadata.tables.values() for index in table.indexes
    }
    actual = set(
        migrated.scalars(
            text("SELECT indexname FROM pg_indexes WHERE schemaname = 'public'")
        )
    )
    assert expected <= actual


@pytest.mark.postgres
def test_complete_metadata_storage(migrated: Connection) -> None:
    """Every field of the richest possible metadata survives a round trip."""
    metadata = rich_metadata()
    session = Session(bind=migrated)
    session.execute(
        text("INSERT INTO provider (id, label, adapter_type) VALUES ('scb', 'SCB', 'pxweb')")
    )
    session.execute(
        text(
            "INSERT INTO dataset (id, provider_id, native_table_id, operator_disabled) "
            "VALUES ('scb-tab1', 'scb', 'TAB1', true)"
        )
    )
    payload = metadata.model_dump(mode="json")
    root = {key: value for key, value in payload.items() if key not in IDENTITY_FIELDS}
    session.execute(
        DatasetMetadata.__table__.insert().values(dataset_id=metadata.table_id, **root)
    )
    for dimension in payload["dimensions"]:
        values = {key: value for key, value in dimension.items() if key != "categories"}
        session.execute(
            Dimension.__table__.insert().values(
                dataset_id=metadata.table_id, language=metadata.language, **values
            )
        )
        for category in dimension["categories"]:
            session.execute(
                Category.__table__.insert().values(
                    dataset_id=metadata.table_id,
                    language=metadata.language,
                    dimension_code=dimension["code"],
                    **category,
                )
            )

    restored = session.execute(DatasetMetadata.__table__.select()).mappings().one()
    assert {key: restored[key] for key in root} == root
    dimensions: list[dict[str, Any]] = []
    stored_dimensions = session.execute(
        Dimension.__table__.select().order_by(Dimension.index)
    ).mappings()
    for row in stored_dimensions:
        values = {
            key: value
            for key, value in row.items()
            if key not in {"dataset_id", "language"}
        }
        categories = session.execute(
            Category.__table__.select()
            .where(Category.dimension_code == row["code"])
            .order_by(Category.index)
        ).mappings()
        values["categories"] = [
            {
                key: value
                for key, value in category.items()
                if key not in {"dataset_id", "language", "dimension_code"}
            }
            for category in categories
        ]
        dimensions.append(values)
    assert (
        NormalizedTableMetadata.model_validate(
            {**payload, **{key: restored[key] for key in root}, "dimensions": dimensions}
        )
        == metadata
    )
    assert session.execute(
        text("SELECT retired, operator_disabled FROM dataset")
    ).mappings().one() == {"retired": False, "operator_disabled": True}


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
