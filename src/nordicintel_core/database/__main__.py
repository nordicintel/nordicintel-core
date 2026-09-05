"""Database command dispatcher."""

from __future__ import annotations

import sys


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] != "migrate":
        print("usage: python -m nordicintel_core.database migrate COMMAND [REVISION]")
        return 2
    from .migration_cli import main as migration_main

    return migration_main(sys.argv[2:])


if __name__ == "__main__":
    raise SystemExit(main())
