"""Standalone migration command used by deployment jobs."""

from __future__ import annotations

import argparse
import os
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from alembic.config import Config


def _configuration(database_url: str) -> Config:
    try:
        from alembic.config import Config
    except ImportError as exc:
        raise SystemExit(
            "Migration support requires the 'migrations' extra: "
            "pip install 'nordicintel-core[migrations]'"
        ) from exc

    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    config = Config()
    config.set_main_option(
        "script_location", str(Path(__file__).with_name("migrations"))
    )
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def _check(config: Config) -> None:
    """Verify the applied revisions without ORM/autogenerate metadata."""
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory
    from sqlalchemy import create_engine

    expected = set(ScriptDirectory.from_config(config).get_heads())
    database_url = config.get_main_option("sqlalchemy.url")
    if database_url is None:
        raise SystemExit("Migration database URL is not configured")
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            actual = set(MigrationContext.configure(connection).get_current_heads())
    finally:
        engine.dispose()
    if actual != expected:
        raise SystemExit(
            f"Database revisions {sorted(actual)} do not match package heads {sorted(expected)}"
        )
    print(f"Database is at expected head: {', '.join(sorted(expected))}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m nordicintel_core.database migrate")
    parser.add_argument("command", choices=("upgrade", "downgrade", "current", "check"))
    parser.add_argument("revision", nargs="?")
    args = parser.parse_args(argv)

    database_url = os.environ.get("NORDICINTEL_DATABASE_URL")
    if not database_url:
        parser.error("NORDICINTEL_DATABASE_URL is required")
    config = _configuration(database_url)

    from alembic import command

    if args.command == "upgrade":
        command.upgrade(config, args.revision or "head")
    elif args.command == "downgrade":
        command.downgrade(config, args.revision or "base")
    elif args.command == "current":
        command.current(config, verbose=False)
    else:
        _check(config)
    return 0
