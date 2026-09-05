"""Test the rewritten definitions directly, without the deferred repository queries."""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import pytest
from psycopg import Connection, sql
from psycopg.types.json import Jsonb
from test_models import rich_metadata

from nordicintel_core.database import connect
from nordicintel_core.database.sql_files import read_migration
from nordicintel_core.models import Category, Dimension, NormalizedTableMetadata

pytestmark = pytest.mark.postgres


@pytest.fixture
def schema() -> Iterator[Connection[dict[str, Any]]]:
    url = os.environ.get("NORDICINTEL_TEST_DATABASE_URL")
    if not url:
        pytest.skip("NORDICINTEL_TEST_DATABASE_URL is not configured")
    with connect(url) as connection, connection.transaction(force_rollback=True):
        name = sql.Identifier("model_schema_" + uuid4().hex)
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(name))
        connection.execute(sql.SQL("SET LOCAL search_path TO {}").format(name))
        connection.execute(read_migration("0001_initial.up.sql"))
        yield connection


def columns(connection: Connection[dict[str, Any]], table: str) -> set[str]:
    return {
        row["column_name"]
        for row in connection.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = %s",
            (table,),
        )
    }


def test_definitions_cover_the_models(schema: Connection[dict[str, Any]]) -> None:
    identity = {"provider_id", "table_id", "native_table_id", "aliases", "dimensions"}
    persistence = {
        "dataset_id",
        "content_hash",
        "last_checked_at",
        "last_harvested_at",
        "search_document",
    }
    assert (
        columns(schema, "dataset_metadata")
        == (set(NormalizedTableMetadata.model_fields) - identity) | persistence
    )
    assert columns(schema, "dimension") == (set(Dimension.model_fields) - {"categories"}) | {
        "dataset_id",
        "language",
    }
    assert columns(schema, "category") == set(Category.model_fields) | {
        "dataset_id",
        "language",
        "dimension_code",
    }
    assert "retired" in columns(schema, "dataset")
    assert "discontinued" not in columns(schema, "dataset")
    assert not {"value", "status", "size", "ordinal"} & columns(schema, "dataset_metadata")


def insert(
    connection: Connection[dict[str, Any]],
    table: str,
    values: dict[str, Any],
    json_fields: set[str],
) -> None:
    """Test-only direct inserts; deliberately do not exercise deferred repositories."""
    connection.execute(
        sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
            sql.Identifier(table),
            sql.SQL(", ").join(map(sql.Identifier, values)),
            sql.SQL(", ").join(sql.Placeholder() for _ in values),
        ),
        [
            Jsonb(value) if name in json_fields and value is not None else value
            for name, value in values.items()
        ],
    )


def test_complete_metadata_storage(schema: Connection[dict[str, Any]]) -> None:
    metadata = rich_metadata()
    schema.execute("INSERT INTO provider (id, label, adapter_type) VALUES ('scb', 'SCB', 'pxweb')")
    schema.execute(
        "INSERT INTO dataset (id, provider_id, native_table_id, operator_disabled) "
        "VALUES ('scb-tab1', 'scb', 'TAB1', true)"
    )
    payload = metadata.model_dump(mode="json")
    excluded = {"provider_id", "table_id", "native_table_id", "aliases", "dimensions"}
    root = {key: value for key, value in payload.items() if key not in excluded}
    insert(
        schema,
        "dataset_metadata",
        {"dataset_id": metadata.table_id, **root},
        {
            "paths",
            "links",
            "link",
            "roles",
            "note_mandatory",
            "px",
            "contacts",
            "comparison_marker",
        },
    )
    for dimension in payload["dimensions"]:
        values = {key: value for key, value in dimension.items() if key != "categories"}
        insert(
            schema,
            "dimension",
            {
                "dataset_id": metadata.table_id,
                "language": metadata.language,
                **values,
            },
            {"extension", "link"},
        )
        for category in dimension["categories"]:
            insert(
                schema,
                "category",
                {
                    "dataset_id": metadata.table_id,
                    "language": metadata.language,
                    "dimension_code": dimension["code"],
                    **category,
                },
                {"unit"},
            )
    restored = schema.execute("SELECT * FROM dataset_metadata").fetchone()
    assert restored is not None
    assert {key: restored[key] for key in root} == root
    dimensions = []
    for row in schema.execute("SELECT * FROM dimension ORDER BY index"):
        row.pop("dataset_id")
        row.pop("language")
        categories = []
        for category in schema.execute(
            "SELECT * FROM category WHERE dimension_code = %s ORDER BY index", (row["code"],)
        ):
            for key in ("dataset_id", "language", "dimension_code"):
                category.pop(key)
            categories.append(category)
        dimensions.append({**row, "categories": categories})
    assert (
        NormalizedTableMetadata.model_validate(
            {
                **payload,
                **{key: restored[key] for key in root},
                "dimensions": dimensions,
            }
        )
        == metadata
    )
    assert schema.execute("SELECT retired, operator_disabled FROM dataset").fetchone() == {
        "retired": False,
        "operator_disabled": True,
    }


def test_definition_downgrade_and_reupgrade(schema: Connection[dict[str, Any]]) -> None:
    schema.execute(read_migration("0001_initial.down.sql"))
    assert not columns(schema, "dataset_metadata")
    schema.execute(read_migration("0001_initial.up.sql"))
    test_definitions_cover_the_models(schema)
