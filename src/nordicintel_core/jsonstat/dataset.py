"""Complete JSON-stat 2.0 Dataset wire model with cube consistency validation."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from math import prod
from typing import Annotated, Any, Literal, Self

from pydantic import Field, model_validator

from ._base import JsonValue, OpenObject, StatisticalObject
from .extensions import DatasetExtension, DimensionExtension, LinkExtension

Number = Annotated[int | float | Decimal, Field(allow_inf_nan=False)]
Observation = Number | str | None
Values = list[Observation] | dict[str, Observation]
Status = str | list[str | None] | dict[str, str]
Position = Annotated[int, Field(ge=0)]


class Unit(OpenObject):
    label: str | None = None
    decimals: int | None = None
    symbol: str | None = None
    position: Literal["start", "end"] | None = None
    base: str | None = None


class Category(StatisticalObject):
    index: list[str] | dict[str, Position] | None = None
    label: dict[str, str] | None = None
    note: dict[str, list[str]] | None = None
    unit: dict[str, Unit] | None = None
    coordinates: dict[str, Annotated[list[Number], Field(min_length=2, max_length=2)]] | None = None
    child: dict[str, list[str]] | None = None

    @property
    def codes(self) -> tuple[str, ...]:
        if isinstance(self.index, dict):
            return tuple(sorted(self.index, key=self.index.__getitem__))
        if self.index is not None:
            return tuple(self.index)
        return tuple(self.label or {})

    @model_validator(mode="after")
    def check_categories(self) -> Self:
        if self.index is None and len(self.label or {}) != 1:
            raise ValueError("index may be omitted only for one labelled category")
        codes = self.codes
        if len(codes) != len(set(codes)):
            raise ValueError("category codes must be unique")
        if isinstance(self.index, dict) and sorted(self.index.values()) != list(range(len(codes))):
            raise ValueError("category positions must be consecutive from zero")
        for name in ("label", "note", "unit", "coordinates", "child"):
            mapping = getattr(self, name)
            if mapping is not None and not set(mapping) <= set(codes):
                raise ValueError(f"category {name} references unknown codes")
        children = self.child or {}
        for parent, descendants in children.items():
            if not set(descendants) <= set(codes) or len(descendants) != len(set(descendants)):
                raise ValueError(f"invalid children for {parent}")
        indegree = dict.fromkeys(codes, 0)
        for descendants in children.values():
            for code in descendants:
                indegree[code] += 1
        ready = [code for code, degree in indegree.items() if degree == 0]
        visited = 0
        while ready:
            visited += 1
            for child in children.get(ready.pop(), []):
                indegree[child] -= 1
                if indegree[child] == 0:
                    ready.append(child)
        if visited != len(codes):
            raise ValueError("category hierarchy contains a cycle")
        return self


class Role(StatisticalObject):
    time: list[str] | None = None
    geo: list[str] | None = None
    metric: list[str] | None = None


class Dimension(StatisticalObject):
    category: Category
    label: str | None = None
    href: str | None = None
    note: list[str] | None = None
    link: dict[str, list[Link]] | None = None
    extension: DimensionExtension | None = None


class Link(StatisticalObject):
    """Relation target, including the specification's optional embedded content."""

    type: str | None = None
    class_: Literal["dataset", "dimension", "collection"] | None = Field(None, alias="class")
    href: str | None = None
    label: str | None = None
    note: list[str] | None = None
    link: dict[str, list[Link]] | None = None
    updated: str | None = None
    source: str | None = None
    extension: LinkExtension | None = None
    category: Category | None = None
    id: list[str] | None = None
    size: list[Position] | None = None
    role: Role | None = None
    dimension: dict[str, Dimension] | None = None
    value: Values | None = None
    status: Status | None = None

    @model_validator(mode="after")
    def check_embedded_cube(self) -> Self:
        if self.id is not None and self.size is not None and self.dimension is not None:
            check_cube(self.id, self.size, self.dimension, self.role, self.value, self.status)
        return self


def check_positions(values: Mapping[str, Any], count: int) -> None:
    for key in values:
        if not key.isascii() or not key.isdecimal() or str(int(key)) != key:
            raise ValueError(f"invalid flat observation position: {key}")
        if int(key) >= count:
            raise ValueError(f"observation position {key} exceeds cube size {count}")


def check_cube(
    ids: list[str],
    sizes: list[int],
    dimensions: dict[str, Dimension],
    role: Role | None,
    value: Values | None,
    status: Status | None,
) -> None:
    if len(set(ids)) != len(ids) or set(dimensions) != set(ids):
        raise ValueError("id must name every dimension exactly once")
    if len(sizes) != len(ids):
        raise ValueError("id and size must have equal lengths")
    for name, count in zip(ids, sizes, strict=True):
        if len(dimensions[name].category.codes) != count:
            raise ValueError(f"size disagrees with categories for {name}")
    if role is not None:
        for names in (role.time, role.geo, role.metric):
            if names is not None and (not set(names) <= set(ids) or len(names) != len(set(names))):
                raise ValueError("roles must reference distinct existing dimensions")
    count = prod(sizes)
    if isinstance(value, list) and len(value) not in (0, count):
        raise ValueError("dense value must be empty metadata or cover the entire cube")
    if isinstance(value, dict):
        check_positions(value, count)
    if isinstance(status, list) and len(status) != count:
        raise ValueError("dense status must cover the entire cube")
    if isinstance(status, dict):
        check_positions(status, count)


class JsonStatDataset(StatisticalObject):
    version: Literal["2.0"]
    class_: Literal["dataset"] = Field(alias="class")
    id: list[str]
    size: list[Position]
    dimension: dict[str, Dimension]
    value: Values
    status: Status | None = None
    role: Role | None = None
    href: str | None = None
    label: str | None = None
    note: list[str] | None = None
    link: dict[str, list[Link]] | None = None
    updated: str | None = None
    source: str | None = None
    error: list[JsonValue] | None = None
    extension: DatasetExtension | None = None

    @model_validator(mode="after")
    def validate_document(self) -> Self:
        from .validation import validate_wire

        check_cube(self.id, self.size, self.dimension, self.role, self.value, self.status)
        validate_wire(self.to_mapping())
        return self

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> Self:
        return cls.model_validate(dict(value))


Dimension.model_rebuild()
Link.model_rebuild()
