"""Normalized table metadata contracts."""

from __future__ import annotations

import hashlib
import json
import re
from enum import StrEnum
from typing import Any

from pydantic import Field, field_validator, model_validator

from ._base import CoreModel

CANONICAL_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


class ServingMode(StrEnum):
    ROUTED = "routed"


class AvailabilityStatus(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class Category(CoreModel):
    code: str = Field(min_length=1)
    label: str = Field(min_length=1)
    ordinal: int = Field(ge=0)
    note: str | None = None
    unit: dict[str, Any] | None = None


class Dimension(CoreModel):
    code: str = Field(min_length=1)
    label: str = Field(min_length=1)
    ordinal: int = Field(ge=0)
    role: str | None = None
    note: str | None = None
    categories: list[Category] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_categories(self) -> Dimension:
        codes = [category.code for category in self.categories]
        ordinals = [category.ordinal for category in self.categories]
        if len(codes) != len(set(codes)):
            raise ValueError("category codes must be unique within a dimension")
        if sorted(ordinals) != list(range(len(ordinals))):
            raise ValueError("category ordinals must be contiguous from zero")
        if ordinals != list(range(len(ordinals))):
            raise ValueError("categories must be supplied in ordinal order")
        return self


class NormalizedTableMetadata(CoreModel):
    provider_id: str
    table_id: str
    native_table_id: str = Field(min_length=1)
    language: str = Field(min_length=1)
    label: str = Field(min_length=1)
    description: str | None = None
    notes: list[str] = Field(default_factory=list)
    source: str | None = None
    start_period: str | None = None
    end_period: str | None = None
    upstream_url: str | None = None
    dimensions: list[Dimension] = Field(min_length=1)
    roles: dict[str, list[str]] = Field(default_factory=dict)
    comparison_marker: dict[str, Any] | None = None
    aliases: list[str] = Field(default_factory=list)

    @field_validator("language")
    @classmethod
    def normalize_language(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("language must not be blank")
        return normalized

    @model_validator(mode="after")
    def validate_structure(self) -> NormalizedTableMetadata:
        if not CANONICAL_ID_PATTERN.fullmatch(self.table_id):
            raise ValueError("table_id must be a canonical table slug")
        codes = [dimension.code for dimension in self.dimensions]
        ordinals = [dimension.ordinal for dimension in self.dimensions]
        if len(codes) != len(set(codes)):
            raise ValueError("dimension codes must be unique")
        if ordinals != list(range(len(ordinals))):
            raise ValueError("dimensions must be supplied in contiguous ordinal order")
        known = set(codes)
        invalid = {code for values in self.roles.values() for code in values} - known
        if invalid:
            raise ValueError(f"role references unknown dimensions: {sorted(invalid)}")
        role_members = [code for values in self.roles.values() for code in values]
        if len(role_members) != len(set(role_members)):
            raise ValueError("a dimension cannot belong to more than one role")
        if len(self.aliases) != len(set(self.aliases)):
            raise ValueError("aliases must be unique")
        return self


def deterministic_hash(value: Any) -> str:
    """Hash adapter-selected JSON content deterministically and without ASCII loss."""
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
