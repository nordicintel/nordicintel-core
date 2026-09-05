import os
import subprocess
import sys
from pathlib import Path

import nordicintel_core


def test_root_exports_only_compatibility_metadata() -> None:
    assert nordicintel_core.__all__ == [
        "SCHEMA_COMPATIBILITY",
        "SCHEMA_HEAD",
        "__version__",
    ]
    assert nordicintel_core.SCHEMA_HEAD == "0001_initial"


def test_migration_assets_ship_with_the_package() -> None:
    """The migration task installs the wheel, so these are not just checkout files."""
    root = Path(nordicintel_core.__file__).parent / "database" / "migrations"
    assert (root / "env.py").is_file()
    assert (root / "script.py.mako").is_file()
    assert (root / "versions" / "0001_initial.py").is_file()


def test_models_import_without_sqlalchemy() -> None:
    """Adapters depend on the contracts alone; only the `db` extra pulls in SQLAlchemy."""
    program = (
        "import sys;"
        "sys.modules['sqlalchemy'] = None;"
        "import nordicintel_core.models as m;"
        "print(m.TableLanguageMetadata.__name__)"
    )
    result = subprocess.run(
        [sys.executable, "-c", program], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "TableLanguageMetadata"


def test_import_does_not_read_database_environment() -> None:
    previous = os.environ.pop("NORDICINTEL_DATABASE_URL", None)
    try:
        assert nordicintel_core.__version__ == "0.1.0"
    finally:
        if previous is not None:
            os.environ["NORDICINTEL_DATABASE_URL"] = previous


def test_dataset_contract_is_self_contained() -> None:
    program = """
import sys
sys.modules["nordicintel_model"] = None
from importlib.resources import files
from nordicintel_core.jsonstat import loads, dumps
from nordicintel_core.models import JsonStatDataset
assert files('nordicintel_core.jsonstat').joinpath('dataset.schema.json').is_file()
payload = (
    '{"version":"2.0","class":"dataset","id":["x"],"size":[1],'
    '"dimension":{"x":{"category":{"index":["a"]}}},"value":[]}'
)
dataset = loads(payload)
assert isinstance(dataset, JsonStatDataset)
assert loads(dumps(dataset)) == dataset
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", program], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
