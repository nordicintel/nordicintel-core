"""Typed statistical metadata shared by the PxWebApi2 Table and Dataset contracts.

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


class Contact(CoreModel):
    raw: str = Field(min_length=1)
    name: str | None = None
    organization: str | None = None
    phone: str | None = None
    mail: str | None = None


class Unit(CoreModel):
    base: str | None = None
    decimals: int | None = None


class RelatedLinkExtension(CoreModel):
    relation: str = Field(min_length=1)
    metaid: str = Field(min_length=1)
    category: str | None = None


class RelatedLink(CoreModel):
    extension: RelatedLinkExtension
    href: str = Field(min_length=1)
    label: str = Field(min_length=1)
    type: str = Field(min_length=1)


class DescribedByLink(CoreModel):
    extension: dict[str, str] | None = None


class DatasetLinks(CoreModel):
    describedby: list[DescribedByLink] | None = None
    related: list[RelatedLink] | None = None


class CodelistInformation(CoreModel):
    """A metadata reference, not a stored codelist or a codelist endpoint."""

    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    type: Literal["Aggregation", "Valueset"]
    links: list[Link]


class PxMetadata(CoreModel):
    infofile: str | None = None
    tableid: str | None = None
    decimals: int | None = None
    official_statistics: bool | None = None
    aggregallowed: bool | None = None
    copyright: bool | None = None
    language: str | None = None
    contents: str | None = None
    description: str | None = None
    descriptiondefault: bool | None = None
    heading: list[str] | None = None
    stub: list[str] | None = None
    matrix: str | None = None
    subject_code: str | None = None
    subject_area: str | None = None
    next_update: str | None = None
    survey: str | None = None
    link: str | None = None
    update_frequency: str | None = None


class DimensionExtension(CoreModel):
    elimination: bool | None = None
    elimination_value_code: str | None = None
    note_mandatory: dict[str, bool] | None = None
    category_note_mandatory: dict[str, dict[str, bool]] | None = None
    refperiod: dict[str, str] | None = None
    show: str | None = None
    codelists: list[CodelistInformation] | None = None
    measuring_type: dict[str, MeasuringType] | None = None
    price_type: dict[str, PriceType] | None = None
    adjustment: dict[str, Adjustment] | None = None
    base_period: dict[str, str] | None = None
    alternative_text: dict[str, str] | None = None
