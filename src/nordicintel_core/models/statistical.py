"""Catalog value types for the PxWebApi2 Table contract.

Names are normalized to snake_case. These are information models, not wire serializers.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from ._base import CoreModel

Role = Literal["time", "geo", "metric"]
TableCategory = Literal["internal", "public", "private", "section"]
TimeUnit = Literal["Annual", "Quarterly", "Monthly", "Weekly", "Other"]
MeasuringType = Literal["Stock", "Flow", "Average", "Other"]
PriceType = Literal["NotApplicable", "Current", "Fixed"]
Adjustment = Literal["None", "SesOnly", "WorkOnly", "WorkAndSes"]


class Link(CoreModel):
    rel: str = Field(min_length=1)
    hreflang: str = Field(min_length=1)
    href: str = Field(min_length=1)


class PathElement(CoreModel):
    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    sort_code: str | None = None
