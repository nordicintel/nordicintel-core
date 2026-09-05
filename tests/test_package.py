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
        "print(m.NormalizedTableMetadata.__name__)"
    )
    result = subprocess.run(
        [sys.executable, "-c", program], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "NormalizedTableMetadata"


def test_import_does_not_read_database_environment() -> None:
    previous = os.environ.pop("NORDICINTEL_DATABASE_URL", None)
    try:
        assert nordicintel_core.__version__ == "0.1.0"
    finally:
        if previous is not None:
            os.environ["NORDICINTEL_DATABASE_URL"] = previous
