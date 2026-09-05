"""Explicit selection and normalized live-data contracts."""

from __future__ import annotations

from pydantic import Field, field_validator, model_validator

from ._base import CoreModel
from .metadata import CANONICAL_ID_PATTERN


class DimensionSelection(CoreModel):
    dimension_code: str = Field(min_length=1)
    category_codes: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_categories(self) -> DimensionSelection:
        if len(self.category_codes) != len(set(self.category_codes)):
            raise ValueError("selected category codes must be unique")
        return self

    @field_validator("dimension_code")
    @classmethod
    def reject_blank_code(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("dimension_code must not be blank")
        return value

    @field_validator("category_codes")
    @classmethod
    def reject_blank_categories(cls, value: list[str]) -> list[str]:
        if any(not code.strip() for code in value):
            raise ValueError("category codes must not be blank")
        return value


class ExplicitSelection(CoreModel):
    table_id: str
    language: str
    dimensions: list[DimensionSelection] = Field(min_length=1)

    @field_validator("language")
    @classmethod
    def normalize_language(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("language must not be blank")
        return normalized

    @field_validator("table_id")
    @classmethod
    def validate_table_id(cls, value: str) -> str:
        if not CANONICAL_ID_PATTERN.fullmatch(value):
            raise ValueError("table_id must be a canonical table slug")
        return value

    @model_validator(mode="after")
    def validate_dimensions(self) -> ExplicitSelection:
        codes = [dimension.dimension_code for dimension in self.dimensions]
        if len(codes) != len(set(codes)):
            raise ValueError("selected dimensions must be unique")
        return self
