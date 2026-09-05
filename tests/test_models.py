from decimal import Decimal

import pytest
from pydantic import ValidationError

from nordicintel_core.models import (
    Category,
    DataCube,
    Dimension,
    DimensionSelection,
    DiscoveryEntry,
    DiscoveryResult,
    HarvestRequest,
    NormalizedTableMetadata,
    deterministic_hash,
)


def category(code: str, ordinal: int) -> Category:
    return Category(code=code, label=f"Etikett {code}", ordinal=ordinal)


def test_harvest_request_normalizes_language_identity() -> None:
    request = HarvestRequest(languages=["SV", " en ", "sv"])
    assert request.languages == ["en", "sv"]


def test_unicode_hash_is_deterministic_and_order_independent() -> None:
    assert deterministic_hash({"b": "Örebro", "a": 1}) == deterministic_hash(
        {"a": 1, "b": "Örebro"}
    )


def test_metadata_rejects_duplicate_categories() -> None:
    with pytest.raises(ValidationError, match="category codes must be unique"):
        Dimension(
            code="region",
            label="Region",
            ordinal=0,
            categories=[category("01", 0), category("01", 1)],
        )


def test_metadata_rejects_unknown_role_dimension() -> None:
    with pytest.raises(ValidationError, match="unknown dimensions"):
        NormalizedTableMetadata(
            provider_id="scb",
            table_id="scb-tab1",
            native_table_id="TAB1",
            language="sv",
            label="Befolkning",
            dimensions=[
                Dimension(
                    code="region",
                    label="Region",
                    ordinal=0,
                    categories=[category("01", 0)],
                )
            ],
            roles={"time": ["year"]},
        )


def test_data_cube_requires_aligned_status_channel() -> None:
    dimensions = [DimensionSelection(dimension_code="year", category_codes=["2024", "2025"])]
    cube = DataCube(
        table_id="scb-tab1",
        language="SV",
        dimensions=dimensions,
        values=[Decimal("1.5"), None],
        statuses=[None, ".."],
    )
    assert cube.language == "sv"
    with pytest.raises(ValidationError, match="statuses length"):
        DataCube(
            table_id="scb-tab1",
            language="sv",
            dimensions=dimensions,
            values=[1, 2],
            statuses=[None],
        )


def test_discovery_rejects_duplicate_source_ids() -> None:
    entry = DiscoveryEntry(source_table_id="TAB1")
    with pytest.raises(ValidationError, match="must be unique"):
        DiscoveryResult(entries=[entry, entry], authoritative=True)
