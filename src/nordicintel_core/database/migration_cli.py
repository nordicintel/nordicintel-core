"""Standalone migration command used by deployment jobs."""

from __future__ import annotations

import argparse
import os
from collections.abc import Sequence
from pathlib import Path


def _configuration(database_url: str):  # type: ignore[no-untyped-def]
    try:
        from alembic.config import Config
    except ImportError as exc:
        raise SystemExit(
            "Migration support requires the 'migrations' extra: "
            "pip install 'nordicintel-core[migrations]'"
        ) from exc

    config = Config()
    config.set_main_option(
        "script_location", str(Path(__file__).with_name("migrations"))
    )
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


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
        command.check(config)
    return 0
