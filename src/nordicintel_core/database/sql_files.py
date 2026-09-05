"""Safe access to packaged, immutable SQL text."""

import re
from functools import lru_cache
from importlib.resources import files

_NAME = re.compile(r"^[a-z0-9][a-z0-9_.-]*\.sql$")


def _read(package: str, name: str) -> str:
    if not _NAME.fullmatch(name):
        raise ValueError("invalid SQL resource name")
    return files(package).joinpath(name).read_text(encoding="utf-8")


@lru_cache(maxsize=256)
def read_query(name: str) -> str:
    return _read("nordicintel_core.database.sql.queries", name)


@lru_cache(maxsize=32)
def read_migration(name: str) -> str:
    return _read("nordicintel_core.database.sql.migrations", name)
