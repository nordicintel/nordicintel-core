from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest

from nordicintel_core.database import (
    HarvestRepository,
    MetadataRepository,
    ProviderRepository,
    ScheduleRepository,
    connect,
)
from nordicintel_core.errors import AdmissionError
from nordicintel_core.models import (
    Category,
    Diagnostic,
    Dimension,
    HarvestRequest,
    ItemStatus,
    JobStatus,
    NormalizedTableMetadata,
    ProviderDefinition,
)

pytestmark = pytest.mark.postgres


def database_url() -> str:
    value = os.environ.get("NORDICINTEL_TEST_DATABASE_URL")
    if not value:
        pytest.skip("NORDICINTEL_TEST_DATABASE_URL is not configured")
    return value.replace("postgresql+psycopg://", "postgresql://")


@pytest.fixture(autouse=True)
def clean_database() -> None:
    with connect(database_url()) as connection:
        connection.execute(
            "TRUNCATE harvest_item, harvest_job, harvest_schedule, category, dimension, "
            "dataset_metadata, dataset_alias, dataset, provider RESTART IDENTITY CASCADE"
        )


def provider(provider_id: str) -> ProviderDefinition:
    return ProviderDefinition(
        id=provider_id,
        label=f"Provider {provider_id}",
        adapter_type="pxweb",
        config={"base_url": "https://example.test"},
    )


def metadata(
    *, provider_id: str = "scb", table_id: str = "scb-tab1", label: str = "Befolkning"
) -> NormalizedTableMetadata:
    return NormalizedTableMetadata(
        provider_id=provider_id,
        table_id=table_id,
        native_table_id="TAB1",
        language="sv",
        label=label,
        comparison_marker={"stamp": label},
        aliases=[f"{provider_id}-old-tab1"],
        dimensions=[
            Dimension(
                code="region",
                label="Region",
                ordinal=0,
                categories=[
                    Category(code="01", label="Stockholm", ordinal=0),
                    Category(code="02", label="Uppsala", ordinal=1),
                ],
            ),
            Dimension(
                code="year",
                label="År",
                ordinal=1,
                categories=[Category(code="2025", label="2025", ordinal=0)],
            ),
        ],
        roles={"time": ["year"], "geo": ["region"]},
    )


def test_metadata_round_trip_search_and_operator_ownership() -> None:
    with connect(database_url()) as connection:
        ProviderRepository(connection).upsert(provider("scb"))
        repository = MetadataRepository(connection)
        assert repository.upsert_language(metadata()) == "scb-tab1"
        repository.set_operator_disabled("scb-tab1", True)
        repository.upsert_language(metadata(label="Folkmängd"))

        restored = repository.get_language("scb-tab1", "SV")
        assert restored is not None
        assert restored.label == "Folkmängd"
        assert [category.code for category in restored.dimensions[0].categories] == ["01", "02"]
        assert restored.roles == {"geo": ["region"], "time": ["year"]}
        assert repository.resolve_id("scb-old-tab1") == "scb-tab1"
        row = connection.execute(
            "SELECT operator_disabled, search_document @@ "
            "plainto_tsquery('simple', 'Folkmängd') AS found "
            "FROM dataset AS d JOIN dataset_metadata AS m ON m.dataset_id = d.id "
            "WHERE d.id = %s AND m.language = 'sv'",
            ("scb-tab1",),
        ).fetchone()
        assert row == {"operator_disabled": True, "found": True}


def test_metadata_and_marker_roll_back_when_alias_conflicts() -> None:
    with connect(database_url()) as connection:
        ProviderRepository(connection).upsert(provider("scb"))
        repository = MetadataRepository(connection)
        repository.upsert_language(metadata())
        second = metadata(table_id="scb-tab2", label="Second").model_copy(
            update={"native_table_id": "TAB2", "aliases": ["scb-tab1"]}
        )
        with pytest.raises(AdmissionError):
            repository.upsert_language(second)

        assert repository.get_language("scb-tab2", "sv") is None
        assert repository.get_language("scb-tab1", "sv").label == "Befolkning"  # type: ignore[union-attr]


def test_queue_serializes_provider_but_skips_to_free_provider() -> None:
    with connect(database_url()) as setup:
        providers = ProviderRepository(setup)
        providers.upsert(provider("scb"))
        providers.upsert(provider("ssb"))
        queue = HarvestRepository(setup)
        first = queue.enqueue("scb", HarvestRequest())
        queue.enqueue("scb", HarvestRequest(force=True))
        third = queue.enqueue("ssb", HarvestRequest())

    owner_one = connect(database_url())
    owner_two = connect(database_url())
    try:
        claimed_one = HarvestRepository(owner_one).claim()
        claimed_two = HarvestRepository(owner_two).claim()
        assert claimed_one is not None and claimed_one.id == first.id
        assert claimed_two is not None and claimed_two.id == third.id
        HarvestRepository(owner_one).finish_job(claimed_one.id, JobStatus.COMPLETED)
        HarvestRepository(owner_two).finish_job(claimed_two.id, JobStatus.COMPLETED)
        HarvestRepository(owner_one).release_provider("scb")
        HarvestRepository(owner_two).release_provider("ssb")
    finally:
        owner_one.close()
        owner_two.close()


def test_item_lifecycle_idempotency_and_cancellation() -> None:
    with connect(database_url()) as connection:
        ProviderRepository(connection).upsert(provider("scb"))
        queue = HarvestRepository(connection)
        job = queue.enqueue("scb", HarvestRequest(languages=["SV"]), request_key="same")
        assert queue.enqueue(
            "scb", HarvestRequest(languages=["sv"]), request_key="same"
        ).id == job.id
        with pytest.raises(AdmissionError, match="another request"):
            queue.enqueue("scb", HarvestRequest(force=True), request_key="same")
        claimed = queue.claim()
        assert claimed is not None
        item = queue.begin_item(claimed.id, "TAB1")
        queue.finish_item(claimed.id, item.id, ItemStatus.SKIPPED)
        assert queue.heartbeat(claimed.id) is False
        assert queue.cancel(claimed.id).cancel_requested is True
        finished = queue.finish_job(claimed.id, JobStatus.CANCELLED)
        assert finished.status is JobStatus.CANCELLED
        queue.release_provider("scb")


def test_schedule_is_atomic_and_stale_job_recovers_after_owner_disconnect() -> None:
    with connect(database_url()) as setup:
        ProviderRepository(setup).upsert(provider("scb"))
        ScheduleRepository(setup).upsert(
            "scb",
            enabled=True,
            every_seconds=60,
            next_run_at=datetime.now(UTC) - timedelta(minutes=1),
            request=HarvestRequest(),
        )
        jobs = ScheduleRepository(setup).enqueue_due()
        assert len(jobs) == 1

    owner = connect(database_url())
    claimed = HarvestRepository(owner).claim()
    assert claimed is not None
    item = HarvestRepository(owner).begin_item(claimed.id, "TAB1")
    owner.execute(
        "UPDATE harvest_job SET heartbeat_at = now() - interval '10 minutes' WHERE id = %s",
        (claimed.id,),
    )
    owner.close()

    with connect(database_url()) as recovery:
        assert HarvestRepository(recovery).recover_stale(180) == [claimed.id]
        recovered = HarvestRepository(recovery).get_job(claimed.id)
        assert recovered is not None and recovered.status is JobStatus.FAILED
        recovered_item = HarvestRepository(recovery).list_items(claimed.id)[0]
        assert recovered_item.id == item.id
        assert recovered_item.status is ItemStatus.FAILED
        assert recovered_item.error == Diagnostic(
            code="worker_abandoned",
            message="The worker session ended before the job completed.",
            stage="interrupted",
        )
