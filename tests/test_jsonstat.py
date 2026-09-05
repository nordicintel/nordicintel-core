"""Core-owned model conformance and regression tests; no external test imports."""

import json
from copy import deepcopy
from decimal import Decimal
from pathlib import Path

import pytest

from nordicintel_core.jsonstat import (
    CatalogLink,
    Category,
    CodelistInformation,
    Contact,
    DatasetExtension,
    Dimension,
    DimensionExtension,
    JsonStatDataset,
    Link,
    LinkExtension,
    PxProperties,
    Role,
    Unit,
    dumps,
    loads,
)
from nordicintel_core.jsonstat.pxweb import validate_pxweb_dataset
from nordicintel_core.models import LanguageMetadata

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def cube() -> dict:
    return {
        "version": "2.0",
        "class": "dataset",
        "id": ["region", "year"],
        "size": [2, 2],
        "dimension": {
            "region": {"category": {"index": {"south": 1, "north": 0}}},
            "year": {"category": {"index": ["2024", "2025"]}},
        },
        "value": [10, None, "suppressed", Decimal("4.1234567890123456789")],
    }


def wire_fields(model: type) -> set[str]:
    return {field.alias or name for name, field in model.model_fields.items()}


def test_every_standard_field_is_explicitly_modelled() -> None:
    schema = json.loads((ROOT / "docs/references/json-stat-dataset.schema.json").read_text())
    definitions = schema["$defs"]
    link = next(iter(definitions["link"]["patternProperties"].values()))["items"]
    dimension = schema["properties"]["dimension"]["additionalProperties"]
    for model, spec in (
        (JsonStatDataset, schema),
        (Category, definitions["category"]),
        (Dimension, dimension),
        (Link, link),
        (Role, schema["properties"]["role"]),
    ):
        assert wire_fields(model) == set(spec["properties"]), model.__name__
    assert {"label", "decimals", "symbol", "position", "base"} <= wire_fields(Unit)


def test_every_pxweb_field_is_explicitly_modelled() -> None:
    schemas = json.loads((ROOT / "docs/references/pxweb-swagger.json").read_text())["components"][
        "schemas"
    ]
    for model, name in (
        (DatasetExtension, "ExtensionRoot"),
        (DimensionExtension, "ExtensionDimension"),
        (PxProperties, "ExtensionRootPx"),
        (Contact, "Contact"),
        (CodelistInformation, "CodelistInformation"),
        (CatalogLink, "Link"),
        (LinkExtension, "RelatedLinkExtension"),
    ):
        assert set(schemas[name]["properties"]) <= wire_fields(model), name


@pytest.mark.parametrize("status", ["estimated", [None, "e", "s", None], {"2": "s"}])
def test_dense_values_all_status_forms_and_decimal_round_trip(cube: dict, status) -> None:
    cube["status"] = status
    dataset = JsonStatDataset.from_mapping(cube)
    restored = loads(dumps(dataset))
    assert restored.to_mapping() == cube
    assert restored.value[-1] == Decimal("4.1234567890123456789")
    assert restored.dimension["region"].category.codes == ("north", "south")


def test_sparse_observations_preserve_positions_and_nulls(cube: dict) -> None:
    cube["value"] = {"3": Decimal("0.1234567890123456789"), "0": None, "2": "missing"}
    cube["status"] = {"3": "e"}
    assert loads(dumps(JsonStatDataset.from_mapping(cube))).to_mapping() == cube


def test_complete_nested_links_units_extensions_and_roles(cube: dict) -> None:
    cube.update(
        href="https://example.test/data",
        label="Population",
        source="Statistical office",
        updated="2025-01-02T10:20:30Z",
        note=["Root note"],
        error=[],
        role={"geo": ["region"], "time": ["year"], "metric": ["region"]},
        extension={"vendor": {"null": None, "number": Decimal("0.000000000000001")}},
    )
    region = cube["dimension"]["region"]
    region.update(label="Region", href="https://example.test/regions", note=["Dimension note"])
    region["category"].update(
        label={"north": "North", "south": "South"},
        note={"north": ["Category note"]},
        child={"north": ["south"]},
        coordinates={"north": [Decimal("18.1234567890123456789"), Decimal("59.1")]},
        unit={
            "north": {
                "base": "person",
                "label": "thousands",
                "decimals": 2,
                "symbol": "p",
                "position": "end",
                "vendor": {"scale": 1000},
            }
        },
    )
    embedded = deepcopy(cube)
    del embedded["version"]
    del embedded["error"]
    embedded["type"] = "application/json"
    cube["link"] = {
        "item": [embedded],
        "describedby": [{"class": "dimension", "category": {"label": {"x": "X"}}}],
        "related": [{"link": {"about": [{"href": "https://example.test/about"}]}}],
    }
    region["link"] = {"describedby": [{"extension": {"code": "region"}}]}
    dataset = JsonStatDataset.from_mapping(cube)
    assert loads(dumps(dataset)).to_mapping() == cube
    assert dataset.link["item"][0].dimension["region"].category.unit["north"].symbol == "p"


def test_constant_dimension_can_omit_index() -> None:
    dataset = JsonStatDataset(
        version="2.0",
        class_="dataset",
        id=["x"],
        size=[1],
        dimension={"x": Dimension(category=Category(label={"only": "Only"}))},
        value=[1],
    )
    assert dataset.dimension["x"].category.codes == ("only",)
    assert "index" not in loads(dumps(dataset)).to_mapping()["dimension"]["x"]["category"]


@pytest.mark.parametrize(
    "change",
    [
        {"version": "1.0"},
        {"class": "collection"},
        {"id": ["region", "region"]},
        {"size": [2]},
        {"size": [3, 2]},
        {"size": [True, 2]},
        {"size": [-1, 2]},
        {"value": [True, 2, 3, 4]},
        {"value": [1, 2]},
        {"value": {"01": 1}},
        {"value": {"-1": 1}},
        {"value": {"4": 1}},
        {"value": {"\u0661": 1}},
        {"value": [float("inf"), 2, 3, 4]},
        {"status": ["e"]},
        {"status": {"4": "e"}},
        {"status": {"0": None}},
        {"role": {"geo": ["unknown"]}},
        {"role": {"other": ["region"]}},
        {"updated": "yesterday"},
        {"href": "not a URI"},
        {"label": None},
        {"unexpected": 1},
        {"note": ["same", "same"]},
    ],
)
def test_invalid_documents_are_rejected(cube: dict, change: dict) -> None:
    cube.update(change)
    with pytest.raises(ValueError):
        JsonStatDataset.from_mapping(cube)


@pytest.mark.parametrize(
    "change",
    [
        {"index": {"north": 1, "south": 2}},
        {"index": ["north", "north"]},
        {"label": {"missing": "Missing"}},
        {"note": {"missing": ["Note"]}},
        {"unit": {"missing": {"base": "person"}}},
        {"coordinates": {"north": [1]}},
        {"child": {"north": ["missing"]}},
        {"child": {"north": ["south"], "south": ["north"]}},
    ],
)
def test_invalid_category_structures_are_rejected(cube: dict, change: dict) -> None:
    cube["dimension"]["region"]["category"].update(change)
    with pytest.raises(ValueError):
        JsonStatDataset.from_mapping(cube)


def test_full_pxweb_fixture_has_typed_extensions() -> None:
    payload = json.loads((ROOT / "tests/fixtures/table_metadata.json").read_text(encoding="utf-8"))
    dataset = JsonStatDataset.from_mapping(payload["metadata"]["dataset"])
    validate_pxweb_dataset(dataset)
    assert isinstance(dataset.extension, DatasetExtension)
    assert dataset.extension.contact[0].organization == "SCB"
    assert dataset.extension.px.official_statistics is True
    assert dataset.dimension["region"].extension.codelists[0].id == "regions"
    assert dataset.dimension["region"].extension.price_type["SE"] == "NotApplicable"
    assert loads(dumps(dataset)).to_mapping() == payload["metadata"]["dataset"]


def test_mutated_nested_content_is_checked_at_output_and_metadata_boundary(cube: dict) -> None:
    dataset = JsonStatDataset.from_mapping(cube)
    dataset.size[0] = 99
    with pytest.raises(ValueError):
        dumps(dataset)
    payload = json.loads((ROOT / "tests/fixtures/table_metadata.json").read_text(encoding="utf-8"))
    payload["metadata"]["dataset"] = dataset
    with pytest.raises(ValueError):
        LanguageMetadata.model_validate(payload["metadata"])


def test_application_schema_exposes_full_dataset_contract() -> None:
    schema = LanguageMetadata.model_json_schema()
    assert set(schema["$defs"]["JsonStatDataset"]["required"]) == {
        "version",
        "class",
        "id",
        "size",
        "dimension",
        "value",
    }
    assert "DimensionExtension" in schema["$defs"]


def test_input_mapping_is_not_retained_by_reference(cube: dict) -> None:
    dataset = JsonStatDataset.from_mapping(cube)
    cube["dimension"]["year"]["category"]["index"].append("2026")
    assert dataset.dimension["year"].category.codes == ("2024", "2025")


@pytest.mark.parametrize(
    "extension",
    [
        {"px": {"official-statistics": "yes"}},
        {"px": {"nextUpdate": "tomorrow"}},
        {"contact": [{"name": "Missing raw contact"}]},
        {"noteMandatory": {"0": 1}},
        {"tags": [42]},
        {"vendor": {"invalid": float("nan")}},
        {"vendor": {"invalid": object()}},
    ],
)
def test_typed_and_open_extensions_reject_invalid_values(cube: dict, extension: dict) -> None:
    cube["extension"] = extension
    with pytest.raises(ValueError):
        JsonStatDataset.from_mapping(cube)


def test_optional_pxweb_nulls_and_unknown_properties_survive(cube: dict) -> None:
    cube["extension"] = {
        "px": {"description": None, "vendor": {"flags": [True, None]}},
        "contact": [{"raw": "Statistics office", "mail": None}],
    }
    assert loads(dumps(JsonStatDataset.from_mapping(cube))).to_mapping() == cube


def test_embedded_link_cube_is_checked(cube: dict) -> None:
    embedded = deepcopy(cube)
    del embedded["version"]
    embedded["size"] = [5, 2]
    cube["link"] = {"item": [embedded]}
    with pytest.raises(ValueError):
        JsonStatDataset.from_mapping(cube)
