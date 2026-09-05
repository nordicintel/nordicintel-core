import os

import nordicintel_core
from nordicintel_core.database.sql_files import read_migration, read_query


def test_root_exports_only_compatibility_metadata() -> None:
    assert nordicintel_core.__all__ == [
        "SCHEMA_COMPATIBILITY",
        "SCHEMA_HEAD",
        "__version__",
    ]
    assert nordicintel_core.SCHEMA_HEAD == "0001_initial"


def test_sql_resources_are_available_and_names_are_validated() -> None:
    assert "CREATE TABLE provider" in read_migration("0001_initial.up.sql")
    assert "INSERT INTO provider" in read_query("provider_upsert.sql")
    try:
        read_query("../secret.sql")
    except ValueError:
        pass
    else:
        raise AssertionError("unsafe resource name was accepted")


def test_import_does_not_read_database_environment() -> None:
    previous = os.environ.pop("NORDICINTEL_DATABASE_URL", None)
    try:
        assert nordicintel_core.__version__ == "0.1.0"
    finally:
        if previous is not None:
            os.environ["NORDICINTEL_DATABASE_URL"] = previous
