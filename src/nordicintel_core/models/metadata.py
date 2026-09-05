"""Table identity and catalog information composed with a JSON-stat Dataset."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from enum import StrEnum
from typing import Annotated, Any, cast

import simplejson
from pydantic import (
    Field,
    PlainSerializer,
    SerializationInfo,
    field_validator,
    model_validator,
)

from nordicintel_core.jsonstat import JsonStatDataset
from nordicintel_core.jsonstat.pxweb import validate_pxweb_dataset

from ._base import CoreModel
from .statistical import Link, PathElement, TableCategory, TimeUnit

CANONICAL_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


def parse_dataset(value: Any) -> JsonStatDataset:
    """Validate the shared Dataset at the application boundary."""
    if not isinstance(value, (JsonStatDataset, Mapping)):
        raise ValueError("dataset must be a JSON-stat object")
    dataset = JsonStatDataset.from_mapping(
        value.to_mapping() if isinstance(value, JsonStatDataset) else value
    )
    validate_pxweb_dataset(dataset)
    return dataset


def _serialize_dataset(value: JsonStatDataset, info: SerializationInfo) -> dict[str, Any]:
    mapping = value.to_mapping()
    if info.mode == "json":
        # Pydantic encodes untyped Decimal values as strings. Dataset numbers must remain numbers.
        # Dataset responses use the JSON-stat codec directly for exact decimal encoding.
        return cast(dict[str, Any], json.loads(simplejson.dumps(mapping, use_decimal=True)))
    return mapping


DatasetValue = Annotated[
    JsonStatDataset,
    PlainSerializer(_serialize_dataset, return_type=dict, when_used="always"),
]


class ServingMode(StrEnum):
    ROUTED = "routed"


class AvailabilityStatus(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class TableCatalogMetadata(CoreModel):
    """The catalog attributes supplied by PxWeb's Table response."""

    label: str = Field(min_length=1)
    updated: str = Field(min_length=1)
    first_period: str = Field(min_length=1)
    last_period: str = Field(min_length=1)
    variable_names: list[str]
    links: list[Link]
    description: str | None = None
    source: str | None = None
    sort_code: str | None = None
    tags: list[str] | None = None
    category: TableCategory | None = None
    discontinued: bool | None = None
    subject_code: str | None = None
    time_unit: TimeUnit | None = None
    paths: list[list[PathElement]] | None = None


class LanguageMetadata(CoreModel):
    """One complete language representation; observations cannot be harvested."""

    language: str = Field(min_length=1)
    catalog: TableCatalogMetadata
    dataset: DatasetValue

    @field_validator("language")
    @classmethod
    def normalize_language(cls, value: str) -> str:
        value = value.strip().lower()
        if not value:
            raise ValueError("language must not be blank")
        return value

    @model_validator(mode="after")
    def metadata_only(self) -> LanguageMetadata:
        validate_pxweb_dataset(self.dataset)
        if not isinstance(self.dataset.value, list) or self.dataset.value:
            raise ValueError("harvested metadata requires value: []")
        if self.dataset.status is not None:
            raise ValueError("harvested metadata cannot contain observation status")
        return self


class TableLanguageMetadata(LanguageMetadata):
    """An accepted language representation associated with a canonical Table."""

    table_id: str

    @field_validator("table_id")
    @classmethod
    def validate_table_id(cls, value: str) -> str:
        if not CANONICAL_ID_PATTERN.fullmatch(value):
            raise ValueError("table_id must be a canonical table identifier")
        return value


class MetadataFetchResult(CoreModel):
    """Adapter output; core establishes canonical identity when accepting it."""

    provider_id: str
    native_table_id: str = Field(min_length=1)
    metadata: LanguageMetadata
    comparison_marker: dict[str, Any] | None = None

    @field_validator("provider_id")
    @classmethod
    def validate_provider_id(cls, value: str) -> str:
        value = value.strip().lower()
        if not CANONICAL_ID_PATTERN.fullmatch(value):
            raise ValueError("provider_id must be a canonical identifier")
        return value

    @field_validator("native_table_id")
    @classmethod
    def validate_native_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("native_table_id must not be blank")
        return value


class TableRecord(CoreModel):
    table_id: str
    provider_id: str
    native_table_id: str
    serving_mode: ServingMode
    operator_disabled: bool
    availability_status: AvailabilityStatus


class TableSearchResult(CoreModel):
    table_id: str
    provider_id: str
    language: str
    label: str
    description: str | None = None
    discontinued: bool
    operator_disabled: bool
    availability_status: AvailabilityStatus
    rank: float = Field(ge=0)


def deterministic_hash(value: Any) -> str:
    """Hash accepted JSON content without operational state."""
    encoded = simplejson.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
