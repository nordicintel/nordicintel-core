"""Complete PxWeb Dataset extension fields from the public OpenAPI contract.

Unknown extension properties remain intact, as required by JSON-stat.
"""

from typing import Annotated, Literal

from pydantic import Field

from ._base import OpenObject, StatisticalObject

Nonempty = Annotated[str, Field(min_length=1)]


class CatalogLink(StatisticalObject):
    rel: Nonempty
    hreflang: Nonempty
    href: Nonempty


class CodelistInformation(StatisticalObject):
    id: Nonempty
    label: Nonempty
    type: Literal["Aggregation", "Valueset"]
    links: list[CatalogLink]


class Contact(StatisticalObject):
    raw: Nonempty
    name: str | None = None
    organization: str | None = None
    phone: str | None = None
    mail: str | None = None


class PxProperties(OpenObject):
    infofile: str | None = None
    tableid: str | None = None
    decimals: int | None = None
    official_statistics: bool | None = Field(None, alias="official-statistics")
    aggregallowed: bool | None = None
    copyright: bool | None = None
    language: str | None = None
    contents: str | None = None
    description: str | None = None
    descriptiondefault: bool | None = None
    heading: list[str] | None = None
    stub: list[str] | None = None
    matrix: str | None = None
    subject_code: str | None = Field(None, alias="subject-code")
    subject_area: str | None = Field(None, alias="subject-area")
    next_update: str | None = Field(
        None,
        alias="nextUpdate",
        pattern=r"^((19|20)\d\d)\-(0?[1-9]|1[012])\-(0?[1-9]|[12][0-9]|3[01])$",
    )
    survey: str | None = None
    link: str | None = None
    update_frequency: str | None = Field(None, alias="updateFrequency")


class DatasetExtension(OpenObject):
    note_mandatory: dict[str, bool] | None = Field(None, alias="noteMandatory")
    px: PxProperties | None = None
    first_period: str | None = Field(None, alias="firstPeriod")
    last_period: str | None = Field(None, alias="lastPeriod")
    tags: list[str] | None = None
    discontinued: bool | None = None
    contact: list[Contact] | None = None


class DimensionExtension(OpenObject):
    elimination: bool | None = None
    elimination_value_code: str | None = Field(None, alias="eliminationValueCode")
    note_mandatory: dict[str, bool] | None = Field(None, alias="noteMandatory")
    category_note_mandatory: dict[str, dict[str, bool]] | None = Field(
        None, alias="categoryNoteMandatory"
    )
    refperiod: dict[str, str] | None = None
    show: str | None = None
    codelists: list[CodelistInformation] | None = None
    measuring_type: dict[str, Literal["Stock", "Flow", "Average", "Other"]] | None = Field(
        None, alias="measuringType"
    )
    price_type: dict[str, Literal["NotApplicable", "Current", "Fixed"]] | None = Field(
        None, alias="priceType"
    )
    adjustment: dict[str, Literal["None", "SesOnly", "WorkOnly", "WorkAndSes"]] | None = None
    base_period: dict[str, str] | None = Field(None, alias="basePeriod")
    alternative_text: dict[str, str] | None = Field(None, alias="alternativeText")


class LinkExtension(DatasetExtension, DimensionExtension):
    code: str | None = None
    relation: str | None = None
    category: str | None = None
    metaid: str | None = None
