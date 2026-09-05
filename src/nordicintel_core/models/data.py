"""Explicit selection and normalized live-data contracts."""

from __future__ import annotations

from math import prod

from pydantic import Field, field_validator, model_validator

from ._base import CoreModel
from .metadata import CANONICAL_ID_PATTERN, DatasetMetadata


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


class Dataset(DatasetMetadata):
    """Normalized JSON-stat Dataset returned by an adapter.

    Metadata responses have an empty value array. Data responses contain one value
    per cell in dimension/category index order. Status is an optional sparse map
    keyed by zero-based cell indexes, as in PxWebApi2, not an aligned second array.
    Wire envelope constants and derived id/size belong to API serialization.
    """

    value: list[float | None] = Field(default_factory=list)
    status: dict[str, str] | None = None

    @model_validator(mode="after")
    def validate_values(self) -> Dataset:
        expected = prod(len(dimension.categories) for dimension in self.dimensions)
        if self.value and len(self.value) != expected:
            raise ValueError(f"value length must equal the dimension product {expected}")
        for key in self.status or {}:
            if not key.isascii() or not key.isdecimal() or str(int(key)) != key:
                raise ValueError("status keys must be canonical nonnegative cell indexes")
            if int(key) >= len(self.value):
                raise ValueError("status references a cell outside value")
        return self
