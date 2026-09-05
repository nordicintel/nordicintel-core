"""Engine and session construction; callers own the lifetime of what they create.

Two engine shapes exist because they have opposing requirements. API request handlers
want a pool that survives idle connections being dropped. A harvest worker must never
change its physical backend: job ownership is enforced with ``pg_backend_pid()`` and with
session-scoped advisory locks, both of which are silently lost when a pool hands out a
different connection. :func:`create_owner_engine` therefore does no pooling at all, and
:func:`owner_session` binds one checked-out connection for the whole job.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

try:
    from sqlalchemy import Engine, create_engine, func, select
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import NullPool
except ImportError as exc:  # pragma: no cover - packaging smoke coverage
    raise ImportError(
        "Database support requires the 'db' extra: pip install 'nordicintel-core[db]'"
    ) from exc


def normalize_url(database_url: str) -> str:
    """Pin the Psycopg 3 driver without requiring it in every configured URL."""
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url


def create_api_engine(database_url: str, **kwargs: object) -> Engine:
    """Build a pooled engine for short, independent request-scoped transactions."""
    return create_engine(normalize_url(database_url), pool_pre_ping=True, **kwargs)


def create_owner_engine(database_url: str, **kwargs: object) -> Engine:
    """Build an unpooled engine for connections that carry job ownership.

    Never add pre-ping or recycling here: both may replace the backend that holds the
    provider advisory lock and matches ``harvest_job.owner_backend_pid``.
    """
    return create_engine(normalize_url(database_url), poolclass=NullPool, **kwargs)


@contextmanager
def session_scope(engine: Engine) -> Iterator[Session]:
    """Yield a session for request-scoped work; repositories own their transactions."""
    with Session(bind=engine) as session:
        yield session


@contextmanager
def owner_session(engine: Engine) -> Iterator[Session]:
    """Yield a session pinned to one physical backend for a whole harvest job.

    The claim, every metadata write, job finalization and the matching advisory unlock
    must all run through this one session. If it is lost, ownership is lost: stop, and
    let recovery establish a new owner rather than reconnecting.
    """
    with engine.connect() as connection, Session(bind=connection) as session:
        yield session


def backend_pid(session: Session) -> int:
    """Report the backend this session is bound to, for ownership assertions."""
    if session.in_transaction():
        return int(session.scalar(select(func.pg_backend_pid())) or 0)
    with session.begin():
        return int(session.scalar(select(func.pg_backend_pid())) or 0)
