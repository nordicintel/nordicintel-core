"""Explicit selection and normalized live-data contracts."""

from __future__ import annotations

from decimal import Decimal

from pydantic import Field, field_validator, model_validator

from ._base import CoreModel


class DimensionSelection(CoreModel):
    dimension_code: str = Field(min_length=1)
    category_codes: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_categories(self) -> DimensionSelection:
        if len(self.category_codes) != len(set(self.category_codes)):
            raise ValueError("selected category codes must be unique")
        return self


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

    @model_validator(mode="after")
    def validate_dimensions(self) -> ExplicitSelection:
        codes = [dimension.dimension_code for dimension in self.dimensions]
        if len(codes) != len(set(codes)):
            raise ValueError("selected dimensions must be unique")
        return self


class DataCube(CoreModel):
    """Row-major observations over ordered dimensions, with an aligned status channel."""

    table_id: str
    language: str
    dimensions: list[DimensionSelection] = Field(min_length=1)
    values: list[int | float | Decimal | None]
    statuses: list[str | None]

    @field_validator("language")
    @classmethod
    def normalize_language(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("language must not be blank")
        return normalized

    @model_validator(mode="after")
    def validate_shape(self) -> DataCube:
        expected = 1
        for dimension in self.dimensions:
            expected *= len(dimension.category_codes)
        if len(self.values) != expected:
            raise ValueError(f"values length must equal cube cell count {expected}")
        if len(self.statuses) != expected:
            raise ValueError(f"statuses length must equal cube cell count {expected}")
        return self
