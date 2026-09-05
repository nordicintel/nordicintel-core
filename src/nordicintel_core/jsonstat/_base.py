"""Common validation and wire serialization for statistical objects."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict

type JsonValue = bool | str | int | float | Decimal | list[JsonValue] | dict[str, JsonValue] | None


class StatisticalObject(BaseModel):
    model_config = ConfigDict(
        strict=True,
        extra="forbid",
        populate_by_name=True,
        revalidate_instances="always",
        allow_inf_nan=False,
    )

    def to_mapping(self) -> dict[str, Any]:
        """Keep wire names, numeric types, and explicitly supplied optional fields."""
        return self.model_dump(mode="python", by_alias=True, exclude_unset=True)


class OpenObject(StatisticalObject):
    """JSON-stat extension and unit objects permit provider-defined properties."""

    model_config = ConfigDict(extra="allow")
    __pydantic_extra__: dict[str, JsonValue]
