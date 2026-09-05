"""Combined Table and Dataset metadata, independent of wire serialization."""

from __future__ import annotations

import hashlib
import json
import re
from enum import StrEnum
from typing import Any

from pydantic import Field, field_validator, model_validator

from ._base import CoreModel
from .statistical import (
    Contact,
    DatasetLinks,
    DimensionExtension,
    Link,
    PathElement,
    PxMetadata,
    Role,
    TableCategory,
    TimeUnit,
    Unit,
)

CANONICAL_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


class ServingMode(StrEnum):
    ROUTED = "routed"


class AvailabilityStatus(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class Category(CoreModel):
    code: str = Field(min_length=1)
    index: int = Field(ge=0)
    label: str | None = None
    notes: list[str] | None = None
    child: list[str] | None = None
    unit: Unit | None = None

    @field_validator("code")
    @classmethod
    def reject_blank_code(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("category code must not be blank")
        return value


class Dimension(CoreModel):
    code: str = Field(min_length=1)
    index: int = Field(ge=0)
    label: str | None = None
    notes: list[str] | None = None
    categories: list[Category]
    extension: DimensionExtension | None = None
    link: DatasetLinks | None = None

    @field_validator("code")
    @classmethod
    def reject_blank_code(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("dimension code must not be blank")
        return value

    @model_validator(mode="after")
    def validate_categories(self) -> Dimension:
        codes = [category.code for category in self.categories]
        indexes = [category.index for category in self.categories]
        if len(codes) != len(set(codes)):
            raise ValueError("category codes must be unique within a dimension")
        if indexes != list(range(len(indexes))):
            raise ValueError("categories must be supplied in contiguous index order")
        known = set(codes)
        for category in self.categories:
            children = category.child or []
            if len(children) != len(set(children)) or set(children) - known:
                raise ValueError("category children must be unique known category codes")
            if category.code in children:
                raise ValueError("a category cannot be its own child")
        if self.extension is not None:
            extension = self.extension
            if (
                extension.elimination_value_code is not None
                and extension.elimination_value_code not in known
            ):
                raise ValueError("elimination value references an unknown category")
            for mapping in (
                extension.category_note_mandatory,
                extension.refperiod,
                extension.measuring_type,
                extension.price_type,
                extension.adjustment,
                extension.base_period,
                extension.alternative_text,
            ):
                if mapping is not None and set(mapping) - known:
                    raise ValueError("dimension extension references unknown categories")
        return self


class DatasetMetadata(CoreModel):
    """Dataset information without redundant envelope fields or observations.

    Root extension fields are flattened here, except the distinct PX metadata object.
    Ordered dimensions determine JSON-stat id and size at serialization time.
    """

    label: str | None = None
    source: str | None = None
    updated: str | None = None
    href: str | None = None
    link: DatasetLinks | None = None
    notes: list[str] | None = None
    roles: dict[Role, list[str]] = Field(default_factory=dict)
    dimensions: list[Dimension]
    note_mandatory: dict[str, bool] | None = None
    px: PxMetadata | None = None
    first_period: str | None = None
    last_period: str | None = None
    tags: list[str] | None = None
    discontinued: bool | None = None
    contacts: list[Contact] | None = None

    @model_validator(mode="after")
    def validate_structure(self) -> DatasetMetadata:
        codes = [dimension.code for dimension in self.dimensions]
        indexes = [dimension.index for dimension in self.dimensions]
        if len(codes) != len(set(codes)):
            raise ValueError("dimension codes must be unique")
        if indexes != list(range(len(indexes))):
            raise ValueError("dimensions must be supplied in contiguous index order")
        known = set(codes)
        for members in self.roles.values():
            if set(members) - known:
                raise ValueError("role references unknown dimensions")
            if len(members) != len(set(members)):
                raise ValueError("role members must be unique")
        if self.px is not None:
            placement = (self.px.heading or []) + (self.px.stub or [])
            if set(placement) - known or len(placement) != len(set(placement)):
                raise ValueError("heading and stub must reference distinct known dimensions")
        return self


class NormalizedTableMetadata(DatasetMetadata):
    """One language's combined Table and Dataset information, plus harvest identity.

    JSON-stat id/size, version and class are derived, not stored.
    Upstream updated is distinct from the repository's own harvest timestamps.
    """

    provider_id: str
    table_id: str
    native_table_id: str = Field(min_length=1)
    language: str = Field(min_length=1)
    label: str = Field(min_length=1)
    updated: str = Field(min_length=1)
    first_period: str = Field(min_length=1)
    last_period: str = Field(min_length=1)
    variable_names: list[str]
    description: str | None = None
    sort_code: str | None = None
    category: TableCategory | None = None
    subject_code: str | None = None
    time_unit: TimeUnit | None = None
    paths: list[list[PathElement]] | None = None
    links: list[Link]
    comparison_marker: dict[str, Any] | None = None
    aliases: list[str] = Field(default_factory=list)

    @field_validator("language")
    @classmethod
    def normalize_language(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("language must not be blank")
        return normalized

    @field_validator("provider_id")
    @classmethod
    def validate_provider_id(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not CANONICAL_ID_PATTERN.fullmatch(normalized):
            raise ValueError("provider_id must be a canonical identifier")
        return normalized

    @field_validator("table_id")
    @classmethod
    def validate_table_id(cls, value: str) -> str:
        if not CANONICAL_ID_PATTERN.fullmatch(value):
            raise ValueError("table_id must be a canonical table slug")
        return value

    @field_validator("aliases")
    @classmethod
    def validate_aliases(cls, value: list[str]) -> list[str]:
        if any(not alias.strip() or "/" in alias for alias in value):
            raise ValueError("aliases must be nonempty URL path segments")
        if len(value) != len(set(value)):
            raise ValueError("aliases must be unique")
        return value


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
    """Hash adapter-selected JSON content deterministically and without ASCII loss."""
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()
