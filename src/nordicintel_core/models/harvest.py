"""Harvest request, discovery, lifecycle, and diagnostic contracts."""

from __future__ import annotations

import json
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field, field_validator, model_validator

from ._base import CoreModel
from .metadata import CANONICAL_ID_PATTERN


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ItemStatus(StrEnum):
    RUNNING = "running"
    UPDATED = "updated"
    SKIPPED = "skipped"
    FAILED = "failed"


class JobTrigger(StrEnum):
    MANUAL = "manual"
    SCHEDULE = "schedule"


class DiagnosticStage(StrEnum):
    DISCOVERY = "discovery"
    FETCH_METADATA = "fetch_metadata"
    NORMALIZE = "normalize"
    PERSIST = "persist"
    INTERRUPTED = "interrupted"


def _language(value: str) -> str:
    normalized = value.strip().lower()
    if not normalized:
        raise ValueError("language must not be blank")
    return normalized


class HarvestRequest(CoreModel):
    """One requested traversal, of one Provider, in one language.

    A catalogue is not the same set of Tables in every language: a publisher may carry a
    Table in Swedish and never publish it in English, and the upstream answer for the
    language it does not have is an error, not an empty result. A run that carried a set
    of languages therefore had to decide, per Table, which of them that Table actually
    had - a question no request could answer and no adapter could be asked without
    inventing a signal for it.

    Naming the language here removes the question instead of answering it. Everything
    downstream is scoped to it: what discovery enumerates, what absence means, and what a
    completed job is a statement about.
    """

    language: str
    table_id: str | None = None
    force: bool = False

    @field_validator("table_id")
    @classmethod
    def validate_table_id(cls, value: str | None) -> str | None:
        if value is not None and not CANONICAL_ID_PATTERN.fullmatch(value):
            raise ValueError("table_id must be a canonical table slug")
        return value

    @field_validator("language")
    @classmethod
    def normalize_language(cls, value: str) -> str:
        return _language(value)


class DiscoveryScope(CoreModel):
    """The scope one discovery call must enumerate.

    ``language`` is required and is the language the enumeration is *in*, not a filter
    applied to it: a listing in one language is the complete inventory for that language
    and says nothing about any other.

    ``table_id`` is canonical and belongs to core; an Adapter cannot resolve it. When a
    worker narrows a job to one Table it resolves that identity first and passes the
    upstream identity in ``native_table_id`` as well, so an Adapter can address the
    Table directly instead of enumerating an entire catalogue. Both are absent for a
    provider-wide traversal, which is the only scope allowed to decide absence.
    """

    language: str
    table_id: str | None = None
    native_table_id: str | None = None

    @field_validator("table_id")
    @classmethod
    def validate_table_id(cls, value: str | None) -> str | None:
        if value is not None and not CANONICAL_ID_PATTERN.fullmatch(value):
            raise ValueError("table_id must be a canonical table slug")
        return value

    @field_validator("native_table_id")
    @classmethod
    def validate_native_table_id(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("native_table_id must not be blank")
        return value

    @field_validator("language")
    @classmethod
    def normalize_language(cls, value: str) -> str:
        return _language(value)

    @model_validator(mode="after")
    def validate_single_table_scope(self) -> DiscoveryScope:
        if self.native_table_id is not None and self.table_id is None:
            raise ValueError("native_table_id requires the canonical table_id it resolves to")
        return self


class DiscoveryEntry(CoreModel):
    """One Table found in the scope's language.

    Membership of the enumeration is the statement that this Table exists in that
    language, so there is nothing further to declare about which languages it has.
    """

    native_table_id: str = Field(min_length=1)
    marker: dict[str, Any] | None = None
    fetch_parameters: dict[str, Any] = Field(default_factory=dict)


class DiscoveryResult(CoreModel):
    """The Tables one discovery call found in ``scope.language``.

    A discovery says what is there. It deliberately says nothing about what is missing:
    nothing in this system acts on a Table's absence, so no flag here claims the
    enumeration was complete enough to be trusted with that.
    """

    scope: DiscoveryScope
    entries: list[DiscoveryEntry]

    @model_validator(mode="after")
    def validate_unique_entries(self) -> DiscoveryResult:
        ids = [entry.native_table_id for entry in self.entries]
        if len(ids) != len(set(ids)):
            raise ValueError("discovery native_table_id values must be unique")
        return self


class LanguageState(CoreModel):
    """What is known about one Table in one language."""

    language: str
    comparison_marker: dict[str, Any] | None = None
    content_hash: str | None = None
    last_checked_at: datetime | None = None
    last_harvested_at: datetime | None = None
    failed: bool = False
    last_error: dict[str, Any] | None = None

    @field_validator("language")
    @classmethod
    def normalize_language(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("language must not be blank")
        return normalized


class Diagnostic(CoreModel):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    stage: DiagnosticStage | None = None
    details: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def cap_serialized_size(self) -> Diagnostic:
        payload = self.model_dump(mode="json")
        if len(json.dumps(payload, ensure_ascii=False).encode()) > 16 * 1024:
            raise ValueError("diagnostic exceeds 16 KiB")
        return self


class HarvestJob(CoreModel):
    id: int
    provider_id: str
    request: HarvestRequest
    trigger: JobTrigger
    status: JobStatus
    request_key: str | None = None
    cancel_requested: bool = False
    created_at: datetime
    started_at: datetime | None = None
    heartbeat_at: datetime | None = None
    finished_at: datetime | None = None
    error: Diagnostic | None = None


class HarvestItem(CoreModel):
    id: int
    job_id: int
    native_table_id: str
    table_id: str | None = None
    status: ItemStatus
    started_at: datetime
    finished_at: datetime | None = None
    error: Diagnostic | None = None


class HarvestSchedule(CoreModel):
    """One recurring traversal of one Provider in one language.

    A Provider served in two languages has two schedules. They can run on different
    intervals, and one being disabled or failing does not silently stop the other.
    """

    provider_id: str
    language: str
    enabled: bool
    every_seconds: int = Field(gt=0)
    next_run_at: datetime
    request: HarvestRequest

    @field_validator("language")
    @classmethod
    def normalize_language(cls, value: str) -> str:
        return _language(value)

    @model_validator(mode="after")
    def validate_request_language(self) -> HarvestSchedule:
        if self.request.language != self.language:
            raise ValueError("a schedule's request must name the schedule's own language")
        return self


class QueueCount(CoreModel):
    provider_id: str
    status: JobStatus
    count: int = Field(ge=1)
