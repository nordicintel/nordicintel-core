"""Explicit Psycopg connection creation; callers own connection lifetime."""

from __future__ import annotations

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError as exc:  # pragma: no cover - packaging smoke coverage
    raise ImportError(
        "Database support requires the 'db' extra: pip install 'nordicintel-core[db]'"
    ) from exc


def connect(database_url: str, *, autocommit: bool = True) -> psycopg.Connection[dict[str, object]]:
    """Open a dict-row connection without reading configuration from the environment."""
    return psycopg.connect(database_url, autocommit=autocommit, row_factory=dict_row)
