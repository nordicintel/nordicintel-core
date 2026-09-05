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


class HarvestRequest(CoreModel):
    table_id: str | None = None
    force: bool = False
    languages: list[str] | None = None

    @field_validator("table_id")
    @classmethod
    def validate_table_id(cls, value: str | None) -> str | None:
        if value is not None and not CANONICAL_ID_PATTERN.fullmatch(value):
            raise ValueError("table_id must be a canonical table slug")
        return value

    @field_validator("languages")
    @classmethod
    def normalize_languages(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        normalized = sorted({language.strip().lower() for language in value})
        if not normalized or any(not language for language in normalized):
            raise ValueError("languages must be omitted or contain nonempty codes")
        return normalized


class DiscoveryScope(CoreModel):
    table_id: str | None = None
    languages: list[str]

    @field_validator("table_id")
    @classmethod
    def validate_table_id(cls, value: str | None) -> str | None:
        if value is not None and not CANONICAL_ID_PATTERN.fullmatch(value):
            raise ValueError("table_id must be a canonical table slug")
        return value

    @field_validator("languages")
    @classmethod
    def normalize_languages(cls, value: list[str]) -> list[str]:
        normalized = list(dict.fromkeys(language.strip().lower() for language in value))
        if not normalized or any(not language for language in normalized):
            raise ValueError("languages must contain nonempty codes")
        return normalized


class DiscoveryEntry(CoreModel):
    source_table_id: str = Field(min_length=1)
    available_languages: list[str] | None = None
    marker: dict[str, Any] | None = None
    fetch_parameters: dict[str, Any] = Field(default_factory=dict)

    @field_validator("available_languages")
    @classmethod
    def normalize_languages(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        normalized = list(dict.fromkeys(language.strip().lower() for language in value))
        if not normalized or any(not language for language in normalized):
            raise ValueError("available_languages must contain nonempty codes")
        return normalized


class DiscoveryResult(CoreModel):
    scope: DiscoveryScope
    entries: list[DiscoveryEntry]
    authoritative: bool

    @model_validator(mode="after")
    def validate_unique_entries(self) -> DiscoveryResult:
        ids = [entry.source_table_id for entry in self.entries]
        if len(ids) != len(set(ids)):
            raise ValueError("discovery source_table_id values must be unique")
        return self


class LanguageState(CoreModel):
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
    source_table_id: str
    table_id: str | None = None
    status: ItemStatus
    started_at: datetime
    finished_at: datetime | None = None
    error: Diagnostic | None = None


class HarvestSchedule(CoreModel):
    provider_id: str
    enabled: bool
    every_seconds: int = Field(gt=0)
    next_run_at: datetime
    request: HarvestRequest


class QueueCount(CoreModel):
    provider_id: str
    status: JobStatus
    count: int = Field(ge=1)
