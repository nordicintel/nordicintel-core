from typing import Any

import pytest
from pydantic import ValidationError

from nordicintel_core.models import (
    Category,
    Dataset,
    DatasetMetadata,
    Dimension,
    DiscoveryEntry,
    DiscoveryResult,
    HarvestRequest,
    NormalizedTableMetadata,
    deterministic_hash,
)


def rich_metadata() -> NormalizedTableMetadata:
    """Exercise every combined Table/Dataset metadata field, including nested extensions."""
    return NormalizedTableMetadata.model_validate(
        {
            "provider_id": "scb",
            "table_id": "scb-tab1",
            "native_table_id": "TAB1",
            "language": " SV ",
            "label": "Befolkning",
            "description": "Örebro län",
            "sort_code": "001",
            "tags": ["befolkning", "ålder"],
            "updated": "2025-03-04",
            "first_period": "2024",
            "last_period": "2025",
            "category": "public",
            "variable_names": ["Region i katalogen"],
            "discontinued": True,
            "source": "SCB",
            "subject_code": "BE",
            "time_unit": "Annual",
            "paths": [[{"id": "BE", "label": "Befolkning", "sort_code": "01"}]],
            "links": [
                {"rel": "self", "hreflang": "sv", "href": "https://example.test/tables/TAB1"}
            ],
            "href": "https://example.test/tables/TAB1/metadata",
            "link": {
                "describedby": [{"extension": {"code": "metadata"}}],
                "related": [
                    {
                        "extension": {
                            "relation": "documentation",
                            "metaid": "m1",
                            "category": "quality",
                        },
                        "href": "https://example.test/quality",
                        "label": "Kvalitet",
                        "type": "text/html",
                    }
                ],
            },
            "notes": ["Första noten", "Andra noten"],
            "note_mandatory": {"0": True, "1": False},
            "roles": {"geo": ["region"]},
            "contacts": [
                {
                    "raw": "SCB, Statistik",
                    "name": "Statistik",
                    "organization": "SCB",
                    "phone": "+46 1",
                    "mail": "stats@example.test",
                }
            ],
            "px": {
                "infofile": "info",
                "tableid": "PX-TAB1",
                "decimals": 0,
                "official_statistics": True,
                "aggregallowed": False,
                "copyright": True,
                "language": "sv",
                "contents": "Antal personer",
                "description": "PX-beskrivning",
                "descriptiondefault": False,
                "heading": ["region"],
                "stub": [],
                "matrix": "M1",
                "subject_code": "BE01",
                "subject_area": "Demografi",
                "next_update": "2026-03-04",
                "survey": "Register",
                "link": "https://example.test/survey",
                "update_frequency": "Årlig",
            },
            "dimensions": [
                {
                    "code": "region",
                    "index": 0,
                    "label": "Region",
                    "notes": ["Dimensionsnot", "Ytterligare not"],
                    "link": {"describedby": [{"extension": {"code": "region"}}]},
                    "extension": {
                        "elimination": True,
                        "elimination_value_code": "SE",
                        "note_mandatory": {"0": True},
                        "category_note_mandatory": {"SE": {"0": True}},
                        "refperiod": {"SE": "2025"},
                        "show": "value",
                        "codelists": [
                            {"id": "regions", "label": "Regioner", "type": "Valueset", "links": []}
                        ],
                        "measuring_type": {"SE": "Stock"},
                        "price_type": {"SE": "NotApplicable"},
                        "adjustment": {"SE": "None"},
                        "base_period": {"SE": "2024"},
                        "alternative_text": {"SE": "Hela Sverige"},
                    },
                    "categories": [
                        {
                            "code": "SE",
                            "index": 0,
                            "label": "Sverige",
                            "notes": ["Land", "Totalt"],
                            "child": ["18"],
                            "unit": {"base": "personer", "decimals": 0},
                        },
                        {"code": "18", "index": 1, "label": None},
                    ],
                }
            ],
            "comparison_marker": {"stamp": "2025-03-04"},
            "aliases": ["scb-old-tab1"],
        }
    )


def test_combined_metadata_preserves_all_information_in_json_round_trip() -> None:
    metadata = rich_metadata()
    assert metadata.language == "sv"
    assert NormalizedTableMetadata.model_validate_json(metadata.model_dump_json()) == metadata
    assert metadata.variable_names != [d.label for d in metadata.dimensions]
    assert metadata.px is not None and metadata.px.description != metadata.description
    assert metadata.dimensions[0].categories[0].notes == ["Land", "Totalt"]
    assert metadata.dimensions[0].categories[1].label is None
    assert not {"id", "size", "value", "status", "version", "class"} & (
        NormalizedTableMetadata.model_fields.keys()
    )


def test_harvest_request_normalizes_language_identity() -> None:
    assert HarvestRequest(languages=["SV", " en ", "sv"]).languages == ["en", "sv"]


def test_unicode_hash_is_deterministic_and_order_independent() -> None:
    assert deterministic_hash({"b": "Örebro", "a": 1}) == deterministic_hash(
        {"a": 1, "b": "Örebro"}
    )
    metadata = rich_metadata()
    assert deterministic_hash(metadata.model_dump(mode="json")) == deterministic_hash(
        NormalizedTableMetadata.model_validate_json(metadata.model_dump_json()).model_dump(
            mode="json"
        )
    )


@pytest.mark.parametrize(
    "field", ["updated", "first_period", "last_period", "links", "variable_names"]
)
def test_required_table_information_is_not_silently_defaulted(field: str) -> None:
    payload = rich_metadata().model_dump()
    del payload[field]
    with pytest.raises(ValidationError):
        NormalizedTableMetadata.model_validate(payload)


@pytest.mark.parametrize(
    "field,value",
    [
        ("table_id", "NOT/a-slug"),
        ("language", " "),
        ("category", "unsupported"),
        ("time_unit", "Daily"),
        ("roles", {"unknown": ["region"]}),
        ("roles", {"geo": ["missing"]}),
        ("roles", {"geo": ["region", "region"]}),
    ],
)
def test_invalid_metadata(field: str, value: Any) -> None:
    payload = rich_metadata().model_dump()
    payload[field] = value
    with pytest.raises(ValidationError):
        NormalizedTableMetadata.model_validate(payload)


def test_index_order_and_duplicate_codes() -> None:
    with pytest.raises(ValidationError, match="category codes must be unique"):
        Dimension(
            code="region",
            index=0,
            categories=[
                Category(code="01", index=0),
                Category(code="01", index=1),
            ],
        )
    with pytest.raises(ValidationError, match="index order"):
        Dimension(code="region", index=0, categories=[Category(code="01", index=1)])
    with pytest.raises(ValidationError):
        Category.model_validate({"code": "01", "ordinal": 0})
    with pytest.raises(ValidationError, match="dimension codes must be unique"):
        DatasetMetadata(
            dimensions=[
                Dimension(code="region", index=0, categories=[]),
                Dimension(code="region", index=1, categories=[]),
            ]
        )
    with pytest.raises(ValidationError, match="index order"):
        DatasetMetadata(dimensions=[Dimension(code="region", index=1, categories=[])])


def test_multiple_roles_do_not_mutate_dimensions() -> None:
    dimension = Dimension(code="year", index=0, categories=[Category(code="2025", index=0)])
    metadata = DatasetMetadata(dimensions=[dimension], roles={"time": ["year"], "metric": ["year"]})
    assert metadata.roles == {"time": ["year"], "metric": ["year"]}
    assert "role" not in dimension.model_dump()


def test_invalid_category_references_and_typed_extensions() -> None:
    for field, value in [
        ("child", ["missing"]),
        ("child", ["SE"]),
        ("unit", {"unsupported": "x"}),
    ]:
        payload = rich_metadata().model_dump()
        payload["dimensions"][0]["categories"][0][field] = value
        with pytest.raises(ValidationError):
            NormalizedTableMetadata.model_validate(payload)
    for field, value in [
        ("elimination_value_code", "missing"),
        ("measuring_type", {"SE": "Wrong"}),
        ("refperiod", {"missing": "2025"}),
        ("price_type", {"SE": "Wrong"}),
    ]:
        payload = rich_metadata().model_dump()
        payload["dimensions"][0]["extension"][field] = value
        with pytest.raises(ValidationError):
            NormalizedTableMetadata.model_validate(payload)


def test_dataset_metadata_and_sparse_status() -> None:
    metadata = rich_metadata()
    payload = metadata.model_dump(include=set(DatasetMetadata.model_fields))
    dataset = Dataset.model_validate(payload)
    assert dataset.value == []
    assert dataset.status is None
    data = Dataset.model_validate({**payload, "value": [1.5, None], "status": {"1": ".."}})
    assert data.dimensions[0].categories[0].label == "Sverige"
    assert data.status == {"1": ".."}
    assert Dataset.model_validate({**payload, "value": [1.5, None]}).status is None
    with pytest.raises(ValidationError, match="dimension product"):
        Dataset.model_validate({**payload, "value": [1.5]})
    for status in ({"2": ".."}, {"-1": ".."}, {"01": ".."}, {"x": ".."}):
        with pytest.raises(ValidationError):
            Dataset.model_validate({**payload, "value": [1.5, None], "status": status})
    with pytest.raises(ValidationError):
        Dataset.model_validate({**payload, "status": {"0": ".."}})


def test_discovery_rejects_duplicate_source_ids() -> None:
    entry = DiscoveryEntry(source_table_id="TAB1")
    with pytest.raises(ValidationError, match="must be unique"):
        DiscoveryResult(scope={"languages": ["sv"]}, entries=[entry, entry], authoritative=True)
