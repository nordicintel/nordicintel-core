"""The single definition of the shared PostgreSQL schema.

Every table, constraint and index lives here. Alembic revisions are generated from
``Base.metadata``; repositories build their statements from these entities. Nothing else
may declare a table, and no instance of these classes crosses a repository boundary:
callers receive the Pydantic contracts in :mod:`nordicintel_core.models`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    MetaData,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Mirrors PostgreSQL's own default names so generated DDL stays recognisable, and gives
# autogenerate stable identities to match constraints across revisions.
NAMING_CONVENTION = {
    "ix": "%(table_name)s_%(column_0_N_name)s_idx",
    "uq": "%(table_name)s_%(column_0_N_name)s_key",
    "ck": "%(table_name)s_%(constraint_name)s_check",
    "fk": "%(table_name)s_%(column_0_N_name)s_fkey",
    "pk": "%(table_name)s_pkey",
}

CANONICAL_ID_CHECK = "~ '^[a-z0-9][a-z0-9._-]*$'"

# A missing value is SQL NULL, never a stored JSON `null`: every jsonb column here is
# checked for its container type, and `null` satisfies none of them.
_JSONB = JSONB(none_as_null=True)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    # Every stored time is an absolute instant; naive timestamps are never correct here.
    type_annotation_map: ClassVar[dict[Any, Any]] = {datetime: DateTime(timezone=True)}


def _jsonb_object(column: str) -> str:
    return f"jsonb_typeof({column}) = 'object'"


def _nullable_jsonb(column: str, kind: str = "object") -> str:
    return f"{column} IS NULL OR jsonb_typeof({column}) = '{kind}'"


class Provider(Base):
    __tablename__ = "provider"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    label: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    website: Mapped[str | None] = mapped_column(Text)
    region: Mapped[str | None] = mapped_column(Text)
    adapter_type: Mapped[str] = mapped_column(Text)
    config: Mapped[dict[str, Any]] = mapped_column(_JSONB, server_default=text("'{}'::jsonb"))
    secret_refs: Mapped[dict[str, str]] = mapped_column(_JSONB, server_default=text("'{}'::jsonb"))
    enabled: Mapped[bool] = mapped_column(server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        CheckConstraint(f"id {CANONICAL_ID_CHECK}", name="id"),
        CheckConstraint("length(label) > 0", name="label"),
        CheckConstraint("region IS NULL OR region ~ '^[A-Z]{2}$'", name="region"),
        CheckConstraint(f"adapter_type {CANONICAL_ID_CHECK}", name="adapter_type"),
        CheckConstraint(_jsonb_object("config"), name="config"),
        CheckConstraint(_jsonb_object("secret_refs"), name="secret_refs"),
    )


class Dataset(Base):
    """Canonical identity, operator controls and worker-owned availability.

    ``retired`` records absence after an authoritative discovery. It is deliberately
    distinct from the publisher's ``dataset_metadata.discontinued`` flag.
    """

    __tablename__ = "dataset"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    provider_id: Mapped[str] = mapped_column(ForeignKey("provider.id"))
    native_table_id: Mapped[str] = mapped_column(Text)
    serving_mode: Mapped[str] = mapped_column(Text, server_default=text("'routed'"))
    retired: Mapped[bool] = mapped_column(server_default=text("false"))
    operator_disabled: Mapped[bool] = mapped_column(server_default=text("false"))
    availability_status: Mapped[str] = mapped_column(Text, server_default=text("'available'"))
    failed_languages: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("'{}'::text[]")
    )
    last_error: Mapped[dict[str, Any] | None] = mapped_column(_JSONB)
    last_harvested_at: Mapped[datetime | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        UniqueConstraint("provider_id", "native_table_id"),
        CheckConstraint(f"id {CANONICAL_ID_CHECK}", name="id"),
        CheckConstraint("length(native_table_id) > 0", name="native_table_id"),
        CheckConstraint("serving_mode IN ('routed')", name="serving_mode"),
        CheckConstraint(
            "availability_status IN ('available', 'unavailable')", name="availability_status"
        ),
        CheckConstraint(_nullable_jsonb("last_error"), name="last_error"),
        Index("dataset_provider_idx", "provider_id", "id"),
    )


class DatasetAlias(Base):
    __tablename__ = "dataset_alias"

    alias: Mapped[str] = mapped_column(Text, primary_key=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("dataset.id"))
    kind: Mapped[str] = mapped_column(Text, server_default=text("'native'"))
    valid_from: Mapped[datetime] = mapped_column(server_default=func.now())
    valid_to: Mapped[datetime | None] = mapped_column()

    __table_args__ = (
        CheckConstraint("length(alias) > 0 AND position('/' in alias) = 0", name="alias"),
        CheckConstraint("valid_to IS NULL OR valid_to >= valid_from", name="validity"),
    )


class DatasetMetadata(Base):
    """One language's combined Table and Dataset metadata.

    Compound typed values are JSONB; ordered dimensions and categories are child
    relations. No observations and no redundant JSON-stat envelope fields are stored.
    """

    __tablename__ = "dataset_metadata"

    dataset_id: Mapped[str] = mapped_column(
        ForeignKey("dataset.id", ondelete="CASCADE"), primary_key=True
    )
    language: Mapped[str] = mapped_column(Text, primary_key=True)
    label: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    sort_code: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    updated: Mapped[str] = mapped_column(Text)
    first_period: Mapped[str] = mapped_column(Text)
    last_period: Mapped[str] = mapped_column(Text)
    variable_names: Mapped[list[str]] = mapped_column(ARRAY(Text))
    category: Mapped[str | None] = mapped_column(Text)
    discontinued: Mapped[bool | None] = mapped_column()
    source: Mapped[str | None] = mapped_column(Text)
    subject_code: Mapped[str | None] = mapped_column(Text)
    time_unit: Mapped[str | None] = mapped_column(Text)
    paths: Mapped[list[Any] | None] = mapped_column(_JSONB)
    links: Mapped[list[Any]] = mapped_column(_JSONB)
    href: Mapped[str | None] = mapped_column(Text)
    link: Mapped[dict[str, Any] | None] = mapped_column(_JSONB)
    notes: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    roles: Mapped[dict[str, Any]] = mapped_column(_JSONB, server_default=text("'{}'::jsonb"))
    note_mandatory: Mapped[dict[str, Any] | None] = mapped_column(_JSONB)
    px: Mapped[dict[str, Any] | None] = mapped_column(_JSONB)
    contacts: Mapped[list[Any] | None] = mapped_column(_JSONB)
    comparison_marker: Mapped[dict[str, Any] | None] = mapped_column(_JSONB)
    content_hash: Mapped[str | None] = mapped_column(Text)
    last_checked_at: Mapped[datetime] = mapped_column(server_default=func.now())
    last_harvested_at: Mapped[datetime] = mapped_column(server_default=func.now())
    search_document: Mapped[Any] = mapped_column(TSVECTOR, server_default=text("''::tsvector"))

    dimensions: Mapped[list[Dimension]] = relationship(
        back_populates="dataset_metadata",
        order_by="Dimension.index",
        lazy="raise_on_sql",
        viewonly=True,
    )

    __table_args__ = (
        CheckConstraint(
            "length(language) > 0 AND language = lower(btrim(language))", name="language"
        ),
        CheckConstraint("length(label) > 0", name="label"),
        CheckConstraint("length(updated) > 0", name="updated"),
        CheckConstraint("length(first_period) > 0", name="first_period"),
        CheckConstraint("length(last_period) > 0", name="last_period"),
        CheckConstraint(
            "category IN ('internal', 'public', 'private', 'section')", name="category"
        ),
        CheckConstraint(
            "time_unit IN ('Annual', 'Quarterly', 'Monthly', 'Weekly', 'Other')", name="time_unit"
        ),
        CheckConstraint(_nullable_jsonb("paths", "array"), name="paths"),
        CheckConstraint("jsonb_typeof(links) = 'array'", name="links"),
        CheckConstraint(_nullable_jsonb("link"), name="link"),
        CheckConstraint(
            f"{_jsonb_object('roles')} "
            "AND roles - ARRAY['time', 'geo', 'metric'] = '{}'::jsonb",
            name="roles",
        ),
        CheckConstraint(_nullable_jsonb("note_mandatory"), name="note_mandatory"),
        CheckConstraint(_nullable_jsonb("px"), name="px"),
        CheckConstraint(_nullable_jsonb("contacts", "array"), name="contacts"),
        CheckConstraint(_nullable_jsonb("comparison_marker"), name="comparison_marker"),
        Index(
            "dataset_metadata_search_idx",
            "search_document",
            postgresql_using="gin",
        ),
    )


class Dimension(Base):
    __tablename__ = "dimension"

    dataset_id: Mapped[str] = mapped_column(Text, primary_key=True)
    language: Mapped[str] = mapped_column(Text, primary_key=True)
    code: Mapped[str] = mapped_column(Text, primary_key=True)
    index: Mapped[int] = mapped_column()
    label: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    extension: Mapped[dict[str, Any] | None] = mapped_column(_JSONB)
    link: Mapped[dict[str, Any] | None] = mapped_column(_JSONB)

    dataset_metadata: Mapped[DatasetMetadata] = relationship(
        back_populates="dimensions", lazy="raise_on_sql", viewonly=True
    )
    categories: Mapped[list[Category]] = relationship(
        back_populates="dimension",
        order_by="Category.index",
        lazy="raise_on_sql",
        viewonly=True,
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["dataset_id", "language"],
            ["dataset_metadata.dataset_id", "dataset_metadata.language"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("dataset_id", "language", "index"),
        CheckConstraint("length(btrim(code)) > 0", name="code"),
        CheckConstraint("index >= 0", name="index"),
    )


class Category(Base):
    __tablename__ = "category"

    dataset_id: Mapped[str] = mapped_column(Text, primary_key=True)
    language: Mapped[str] = mapped_column(Text, primary_key=True)
    dimension_code: Mapped[str] = mapped_column(Text, primary_key=True)
    code: Mapped[str] = mapped_column(Text, primary_key=True)
    index: Mapped[int] = mapped_column()
    label: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    child: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    unit: Mapped[dict[str, Any] | None] = mapped_column(_JSONB)

    dimension: Mapped[Dimension] = relationship(
        back_populates="categories", lazy="raise_on_sql", viewonly=True
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["dataset_id", "language", "dimension_code"],
            ["dimension.dataset_id", "dimension.language", "dimension.code"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("dataset_id", "language", "dimension_code", "index"),
        CheckConstraint("length(btrim(code)) > 0", name="code"),
        CheckConstraint("index >= 0", name="index"),
    )


class HarvestSchedule(Base):
    __tablename__ = "harvest_schedule"

    provider_id: Mapped[str] = mapped_column(ForeignKey("provider.id"), primary_key=True)
    enabled: Mapped[bool] = mapped_column(server_default=text("true"))
    every_seconds: Mapped[int] = mapped_column()
    next_run_at: Mapped[datetime] = mapped_column()
    request: Mapped[dict[str, Any]] = mapped_column(
        _JSONB,
        # Built rather than written as a JSON literal: text() would read ':null' as a
        # bind parameter, both here and in the revision autogenerate renders from it.
        server_default=text(
            "jsonb_build_object('table_id', NULL, 'force', false, 'languages', NULL)"
        ),
    )

    __table_args__ = (
        CheckConstraint("every_seconds > 0", name="every_seconds"),
        CheckConstraint(
            f"{_jsonb_object('request')} AND request->'table_id' = 'null'::jsonb",
            name="request",
        ),
        Index("harvest_schedule_due_idx", "next_run_at", postgresql_where=text("enabled")),
    )


class HarvestJob(Base):
    """The queued row is also the execution record.

    ``owner_backend_pid`` is the ownership token: a worker may only advance a job from the
    same physical backend that claimed it.
    """

    __tablename__ = "harvest_job"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    provider_id: Mapped[str] = mapped_column(ForeignKey("provider.id"))
    request: Mapped[dict[str, Any]] = mapped_column(_JSONB)
    trigger: Mapped[str] = mapped_column(Text, server_default=text("'manual'"))
    request_key: Mapped[str | None] = mapped_column(Text, unique=True)
    status: Mapped[str] = mapped_column(Text, server_default=text("'queued'"))
    cancel_requested: Mapped[bool] = mapped_column(server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column()
    heartbeat_at: Mapped[datetime | None] = mapped_column()
    owner_backend_pid: Mapped[int | None] = mapped_column()
    finished_at: Mapped[datetime | None] = mapped_column()
    error: Mapped[dict[str, Any] | None] = mapped_column(_JSONB)

    __table_args__ = (
        CheckConstraint(_jsonb_object("request"), name="request"),
        CheckConstraint("trigger IN ('manual', 'schedule')", name="trigger"),
        CheckConstraint(
            "request_key IS NULL OR length(request_key) BETWEEN 1 AND 200", name="request_key"
        ),
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed', 'cancelled')", name="status"
        ),
        CheckConstraint(
            "status <> 'running' OR (started_at IS NOT NULL AND heartbeat_at IS NOT NULL "
            "AND owner_backend_pid IS NOT NULL)",
            name="running_state",
        ),
        CheckConstraint(
            "status NOT IN ('completed', 'failed', 'cancelled') OR finished_at IS NOT NULL",
            name="terminal_state",
        ),
        CheckConstraint("status <> 'failed' OR error IS NOT NULL", name="failure_error"),
        CheckConstraint(_nullable_jsonb("error"), name="error"),
        Index(
            "harvest_job_queue_idx",
            "created_at",
            "id",
            postgresql_where=text("status = 'queued'"),
        ),
        Index(
            "harvest_job_one_running_provider_idx",
            "provider_id",
            unique=True,
            postgresql_where=text("status = 'running'"),
        ),
        Index(
            "harvest_job_provider_history_idx",
            "provider_id",
            text("created_at DESC"),
            text("id DESC"),
        ),
        Index(
            "harvest_job_stale_idx",
            "heartbeat_at",
            postgresql_where=text("status = 'running'"),
        ),
    )


class HarvestItem(Base):
    __tablename__ = "harvest_item"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    job_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("harvest_job.id", ondelete="CASCADE")
    )
    source_table_id: Mapped[str] = mapped_column(Text)
    dataset_id: Mapped[str | None] = mapped_column(ForeignKey("dataset.id"))
    status: Mapped[str] = mapped_column(Text, server_default=text("'running'"))
    started_at: Mapped[datetime] = mapped_column(server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column()
    error: Mapped[dict[str, Any] | None] = mapped_column(_JSONB)

    __table_args__ = (
        UniqueConstraint("job_id", "source_table_id"),
        CheckConstraint("length(source_table_id) > 0", name="source_table_id"),
        CheckConstraint(
            "status IN ('running', 'updated', 'skipped', 'failed')", name="status"
        ),
        CheckConstraint("status = 'running' OR finished_at IS NOT NULL", name="terminal_state"),
        CheckConstraint("status <> 'failed' OR error IS NOT NULL", name="failure_error"),
        CheckConstraint(_nullable_jsonb("error"), name="error"),
        Index("harvest_item_job_idx", "job_id", "status", "id"),
        Index("harvest_item_dataset_idx", "dataset_id", text("started_at DESC")),
    )
