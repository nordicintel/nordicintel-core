import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from nordicintel_core.jsonstat import JsonStatDataset, dumps, loads
from nordicintel_core.models import (
    DiscoveryEntry,
    DiscoveryResult,
    HarvestRequest,
    LanguageMetadata,
    MetadataFetchResult,
    TableLanguageMetadata,
    deterministic_hash,
)
from nordicintel_core.models.metadata import parse_dataset


def rich_metadata() -> MetadataFetchResult:
    return MetadataFetchResult.model_validate_json(
        (Path(__file__).parent / "fixtures/table_metadata.json").read_text(encoding="utf-8")
    )


def test_jsonstat_composition_round_trip() -> None:
    result = rich_metadata()
    assert isinstance(result.metadata.dataset, JsonStatDataset)
    assert result.metadata.language == "sv"
    assert result.metadata.catalog.label != result.metadata.dataset.label
    wire = result.metadata.dataset.to_mapping()
    assert wire["value"] == []
    assert wire["id"] == ["region"]
    assert wire["size"] == [2]
    assert wire["link"]["related"][0]["extension"]["metaid"] == "m1"
    assert wire["dimension"]["region"]["extension"]["priceType"]["SE"] == "NotApplicable"
    assert MetadataFetchResult.model_validate_json(result.model_dump_json()) == result
    assert loads(dumps(result.metadata.dataset)).to_mapping() == wire
    assert "aliases" not in result.model_dump()
    assert "comparison_marker" not in result.metadata.model_dump()


def test_same_dataset_type_serves_live_data() -> None:
    dataset = rich_metadata().metadata.dataset
    live = JsonStatDataset.from_mapping(
        {**dataset.to_mapping(), "value": [1.5, None], "status": {"1": ".."}}
    )
    assert type(live) is type(dataset)
    assert parse_dataset(live).to_mapping()["value"] == [1.5, None]
    assert loads(dumps(live)).to_mapping()["status"] == {"1": ".."}
    with pytest.raises(ValueError):
        parse_dataset({**dataset.to_mapping(), "value": [1.5]})


@pytest.mark.parametrize(
    "changes", [{"value": [1.5, None]}, {"value": {}}, {"status": {"0": ".."}}]
)
def test_harvest_rejects_observations(changes: dict) -> None:
    payload = rich_metadata().metadata.model_dump(mode="json")
    payload["dataset"].update(changes)
    with pytest.raises(ValueError):
        LanguageMetadata.model_validate(payload)


@pytest.mark.parametrize(
    "mutator",
    [
        lambda p: p.update(aliases=["old-table"]),
        lambda p: p["metadata"].update(language=" "),
        lambda p: p["metadata"]["catalog"].update(time_unit="Daily"),
        lambda p: p["metadata"]["dataset"].update(size=[3]),
        lambda p: p["metadata"]["dataset"].update(role={"geo": ["missing"]}),
        lambda p: p["metadata"]["dataset"]["dimension"]["region"]["category"].update(
            index={"SE": 1, "18": 2}
        ),
        lambda p: p["metadata"]["dataset"]["extension"].update(noteMandatory={"9": True}),
        lambda p: p["metadata"]["dataset"]["dimension"]["region"]["extension"].update(
            refperiod={"missing": "2025"}
        ),
        lambda p: p["metadata"]["dataset"]["dimension"]["region"]["extension"].update(
            priceType={"SE": "Wrong"}
        ),
    ],
)
def test_invalid_metadata(mutator) -> None:
    payload = json.loads(rich_metadata().model_dump_json())
    mutator(payload)
    with pytest.raises(ValueError):
        MetadataFetchResult.model_validate(payload)


@pytest.mark.parametrize(
    "field", ["updated", "first_period", "last_period", "links", "variable_names"]
)
def test_required_catalog_information_is_not_fabricated(field: str) -> None:
    payload = rich_metadata().metadata.model_dump(mode="json")
    del payload["catalog"][field]
    with pytest.raises(ValidationError):
        LanguageMetadata.model_validate(payload)


def test_accepted_table_contains_no_harvest_fields() -> None:
    metadata = rich_metadata().metadata
    accepted = TableLanguageMetadata(table_id="scb-tab1", **metadata.model_dump())
    assert set(accepted.model_dump()) == {"table_id", "language", "catalog", "dataset"}
    with pytest.raises(ValidationError):
        TableLanguageMetadata(table_id="NOT/a-slug", **metadata.model_dump())


def test_unknown_extensions_and_order_survive() -> None:
    payload = rich_metadata().metadata.model_dump(mode="json")
    payload["dataset"]["extension"]["vendor"] = {"nested": [1, False, "Örebro"]}
    category = payload["dataset"]["dimension"]["region"]["category"]
    category["index"] = {"18": 1, "SE": 0}
    restored = LanguageMetadata.model_validate(payload)
    assert restored.dataset.dimension["region"].category.codes == ("SE", "18")
    assert restored.dataset.to_mapping()["extension"]["vendor"] == {"nested": [1, False, "Örebro"]}


def test_harvest_request_normalizes_languages() -> None:
    assert HarvestRequest(languages=["SV", " en ", "sv"]).languages == ["en", "sv"]


def test_unicode_hash_is_deterministic() -> None:
    assert deterministic_hash({"b": "Örebro", "a": 1}) == deterministic_hash(
        {"a": 1, "b": "Örebro"}
    )


def test_discovery_rejects_duplicate_source_ids() -> None:
    entry = DiscoveryEntry(native_table_id="TAB1")
    with pytest.raises(ValidationError, match="must be unique"):
        DiscoveryResult(scope={"languages": ["sv"]}, entries=[entry, entry], authoritative=True)
