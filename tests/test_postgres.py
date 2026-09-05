from __future__ import annotations

import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from threading import Barrier

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session
from test_models import rich_metadata

from nordicintel_core.database import (
    HarvestRepository,
    MetadataRepository,
    ProviderRepository,
    ScheduleRepository,
    backend_pid,
    create_owner_engine,
)
from nordicintel_core.errors import AdmissionError, OwnershipLost
from nordicintel_core.models import (
    Diagnostic,
    DiscoveryResult,
    DiscoveryScope,
    HarvestRequest,
    ItemStatus,
    JobStatus,
    MetadataFetchResult,
    ProviderDefinition,
)

pytestmark = pytest.mark.postgres


def database_url() -> str:
    value = os.environ.get("NORDICINTEL_TEST_DATABASE_URL")
    if not value:
        pytest.skip("NORDICINTEL_TEST_DATABASE_URL is not configured")
    return value


@contextmanager
def owner() -> Iterator[Session]:
    """One session on one dedicated backend, exactly as a worker holds it."""
    engine = create_owner_engine(database_url())
    try:
        with engine.connect() as connection, Session(bind=connection) as session:
            yield session
    finally:
        engine.dispose()


@pytest.fixture(autouse=True)
def clean_database() -> None:
    with owner() as session, session.begin():
        session.execute(
            text(
                "TRUNCATE harvest_item, harvest_job, harvest_schedule, table_metadata, "
                "table_language_state, table_registry, provider RESTART IDENTITY CASCADE"
            )
        )


def provider(provider_id: str) -> ProviderDefinition:
    return ProviderDefinition(
        id=provider_id,
        label=f"Provider {provider_id}",
        adapter_type="pxweb",
        config={"base_url": "https://example.test"},
    )


def metadata(
    *,
    provider_id: str = "scb",
    table_id: str = "scb-tab1",
    label: str = "Befolkning",
    language: str = "sv",
) -> MetadataFetchResult:
    payload = rich_metadata().model_dump(mode="json")
    payload["provider_id"] = provider_id
    payload["native_table_id"] = table_id.split("-")[-1].upper()
    payload["metadata"]["language"] = language
    payload["metadata"]["catalog"]["label"] = label
    payload["metadata"]["catalog"]["discontinued"] = False
    payload["comparison_marker"] = {"stamp": label}
    payload["metadata"]["dataset"] = {
        "version": "2.0",
        "class": "dataset",
        "id": ["region", "year"],
        "size": [2, 1],
        "role": {"geo": ["region"], "time": ["year"]},
        "dimension": {
            "region": {
                "label": "Region",
                "category": {"index": ["01", "02"], "label": {"01": "Stockholm", "02": "Uppsala"}},
            },
            "year": {"label": "År", "category": {"index": ["2025"], "label": {"2025": "2025"}}},
        },
        "value": [],
    }
    return MetadataFetchResult.model_validate(payload)


def start_job(session: Session, provider_id: str = "scb") -> int:
    queue = HarvestRepository(session)
    queued = queue.enqueue(provider_id, HarvestRequest())
    claimed = queue.claim()
    assert claimed is not None and claimed.id == queued.id
    return claimed.id


def test_metadata_round_trip_search_and_operator_ownership() -> None:
    with owner() as session:
        ProviderRepository(session).upsert(provider("scb"))
        job_id = start_job(session)
        repository = MetadataRepository(session)
        assert repository.upsert_language(job_id, metadata()) == "scb-tab1"
        assert repository.search("Befolkning")[0].table_id == "scb-tab1"
        repository.set_operator_disabled("scb-tab1", True)
        repository.upsert_language(job_id, metadata(label="Folkmängd"))

        restored = repository.get_language("scb-tab1", "SV")
        assert restored is not None
        assert restored.catalog.label == "Folkmängd"
        assert list(restored.dataset.dimensions[0].category.codes) == ["01", "02"]
        assert restored.dataset.role.to_mapping() == {"geo": ["region"], "time": ["year"]}
        assert repository.resolve_id("scb-tab1") == "scb-tab1"
        assert repository.resolve_id("scb-old-tab1") is None
        # A harvest must not clear an operator's decision, so the table stays out of search.
        assert repository.search("Folkmängd") == []
        with session.begin():
            row = session.execute(
                text(
                    "SELECT operator_disabled, search_document @@ "
                    "plainto_tsquery('simple', 'Folkmängd') AS found "
                    "FROM table_registry AS d JOIN table_metadata AS m ON m.table_id = d.id "
                    "WHERE d.id = :table_id AND m.language = 'sv'"
                ),
                {"table_id": "scb-tab1"},
            ).one()
        assert (row.operator_disabled, row.found) == (True, True)


def test_search_indexes_dimension_and_category_labels() -> None:
    with owner() as session:
        ProviderRepository(session).upsert(provider("scb"))
        job_id = start_job(session)
        repository = MetadataRepository(session)
        repository.upsert_language(job_id, metadata())
        assert [result.table_id for result in repository.search("Uppsala")] == ["scb-tab1"]
        assert [result.table_id for result in repository.search("Region")] == ["scb-tab1"]


def test_retired_and_discontinued_tables_leave_the_default_search() -> None:
    with owner() as session:
        ProviderRepository(session).upsert(provider("scb"))
        job_id = start_job(session)
        repository = MetadataRepository(session)
        repository.upsert_language(job_id, metadata())
        assert len(repository.search("Befolkning")) == 1
        with session.begin():
            session.execute(text("UPDATE table_registry SET retired = true"))
        assert repository.search("Befolkning") == []
        assert len(repository.search("Befolkning", include_discontinued=True)) == 1
        with session.begin():
            session.execute(
                text("UPDATE table_registry SET retired = false"),
            )
            session.execute(text("UPDATE table_metadata SET discontinued = true"))
        assert repository.search("Befolkning") == []
        assert len(repository.search("Befolkning", include_discontinued=True)) == 1


def test_language_failure_does_not_invalidate_successful_language_state() -> None:
    with owner() as session:
        ProviderRepository(session).upsert(provider("scb"))
        job_id = start_job(session)
        repository = MetadataRepository(session)
        repository.upsert_language(job_id, metadata())
        english = metadata(label="Population", language="en")
        repository.upsert_language(job_id, english)
        repository.record_failure(
            job_id,
            "scb-tab1",
            Diagnostic(code="upstream_timeout", message="Metadata request timed out."),
            language="sv",
        )
        repository.upsert_language(job_id, english)

        states = repository.load_language_state("scb-tab1")
        assert states["sv"].failed is True
        assert states["en"].failed is False
        assert repository.get_language("scb-tab1", "sv") is not None


def test_metadata_and_marker_roll_back_on_persistence_failure(monkeypatch) -> None:
    with owner() as session:
        ProviderRepository(session).upsert(provider("scb"))
        job_id = start_job(session)
        repository = MetadataRepository(session)
        repository.upsert_language(job_id, metadata())
        before = repository.load_language_state("scb-tab1")["sv"]

        def fail(*args):
            raise RuntimeError("injected failure after metadata and marker writes")

        monkeypatch.setattr(repository, "_mark_success", fail)
        with pytest.raises(RuntimeError, match="injected"):
            repository.upsert_language(job_id, metadata(label="Changed"))
        assert repository.get_language("scb-tab1", "sv").catalog.label == "Befolkning"
        assert repository.load_language_state("scb-tab1")["sv"] == before


def test_first_language_failure_has_state_without_metadata() -> None:
    with owner() as session:
        ProviderRepository(session).upsert(provider("scb"))
        job_id = start_job(session)
        repository = MetadataRepository(session)
        repository.upsert_language(job_id, metadata())
        repository.record_failure(
            job_id, "scb-tab1", Diagnostic(code="timeout", message="Timeout"), language="en"
        )
        assert repository.get_language("scb-tab1", "en") is None
        state = repository.load_language_state("scb-tab1")["en"]
        assert state.failed and state.comparison_marker is None and state.last_harvested_at is None
        repository.upsert_language(job_id, metadata(language="en"))
        assert not repository.load_language_state("scb-tab1")["en"].failed


def test_retirement_requires_authoritative_provider_wide_discovery() -> None:
    with owner() as session:
        ProviderRepository(session).upsert(provider("scb"))
        job_id = start_job(session)
        repository = MetadataRepository(session)
        repository.upsert_language(job_id, metadata())
        incomplete = DiscoveryResult(
            scope=DiscoveryScope(languages=["sv"]), entries=[], authoritative=False
        )
        with pytest.raises(ValueError, match="authoritative"):
            repository.retire_unseen(job_id, "scb", incomplete)
        authoritative = incomplete.model_copy(update={"authoritative": True})
        assert repository.retire_unseen(job_id, "scb", authoritative) == ["scb-tab1"]


def test_queue_serializes_provider_but_skips_to_free_provider() -> None:
    with owner() as setup:
        providers = ProviderRepository(setup)
        providers.upsert(provider("scb"))
        providers.upsert(provider("ssb"))
        queue = HarvestRepository(setup)
        first = queue.enqueue("scb", HarvestRequest())
        queue.enqueue("scb", HarvestRequest(force=True))
        third = queue.enqueue("ssb", HarvestRequest())

    with owner() as owner_one, owner() as owner_two:
        claimed_one = HarvestRepository(owner_one).claim()
        claimed_two = HarvestRepository(owner_two).claim()
        assert claimed_one is not None and claimed_one.id == first.id
        assert claimed_two is not None and claimed_two.id == third.id
        HarvestRepository(owner_one).finish_job(claimed_one.id, JobStatus.COMPLETED)
        HarvestRepository(owner_two).finish_job(claimed_two.id, JobStatus.COMPLETED)
        HarvestRepository(owner_one).release_provider("scb")
        HarvestRepository(owner_two).release_provider("ssb")


def test_item_lifecycle_idempotency_and_cancellation() -> None:
    with owner() as session:
        ProviderRepository(session).upsert(provider("scb"))
        queue = HarvestRepository(session)
        job = queue.enqueue("scb", HarvestRequest(languages=["SV"]), request_key="same")
        assert (
            queue.enqueue("scb", HarvestRequest(languages=["sv"]), request_key="same").id == job.id
        )
        with pytest.raises(AdmissionError, match="another request"):
            queue.enqueue("scb", HarvestRequest(force=True), request_key="same")
        claimed = queue.claim()
        assert claimed is not None
        item = queue.begin_item(claimed.id, "TAB1")
        queue.finish_item(claimed.id, item.id, ItemStatus.SKIPPED)
        assert queue.heartbeat(claimed.id) is False
        ProviderRepository(session).set_enabled("scb", False)
        assert queue.heartbeat(claimed.id) is True
        ProviderRepository(session).set_enabled("scb", True)
        assert queue.cancel(claimed.id).cancel_requested is True
        finished = queue.finish_job(claimed.id, JobStatus.CANCELLED)
        assert finished.status is JobStatus.CANCELLED
        queue.release_provider("scb")


def test_cancelled_queued_job_cannot_be_claimed() -> None:
    with owner() as session:
        ProviderRepository(session).upsert(provider("scb"))
        queue = HarvestRepository(session)
        job = queue.enqueue("scb", HarvestRequest())
        assert queue.cancel(job.id).status is JobStatus.CANCELLED
        assert queue.claim() is None


def test_concurrent_idempotent_admission_returns_one_job() -> None:
    with owner() as session:
        ProviderRepository(session).upsert(provider("scb"))
    barrier = Barrier(2)

    def enqueue() -> int:
        with owner() as session:
            barrier.wait()
            return (
                HarvestRepository(session)
                .enqueue("scb", HarvestRequest(languages=["sv"]), request_key="concurrent")
                .id
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        ids = list(executor.map(lambda _: enqueue(), range(2)))
    assert ids[0] == ids[1]
    with owner() as session:
        assert len(HarvestRepository(session).list_jobs()) == 1


def test_scheduler_singleton_lock_is_session_owned() -> None:
    with owner() as first, owner() as second:
        assert ScheduleRepository(first).try_singleton_lock() is True
        assert ScheduleRepository(second).try_singleton_lock() is False
        ScheduleRepository(first).release_singleton_lock()
        assert ScheduleRepository(second).try_singleton_lock() is True
        ScheduleRepository(second).release_singleton_lock()


def test_schedule_is_atomic_and_stale_job_recovers_after_owner_disconnect() -> None:
    with owner() as setup:
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
        assert ScheduleRepository(setup).enqueue_due() == []

    engine = create_owner_engine(database_url())
    connection = engine.connect()
    owner_session = Session(bind=connection)
    claimed = HarvestRepository(owner_session).claim()
    assert claimed is not None
    item = HarvestRepository(owner_session).begin_item(claimed.id, "TAB1")
    with owner_session.begin():
        owner_session.execute(
            text(
                "UPDATE harvest_job SET heartbeat_at = now() - interval '10 minutes' "
                "WHERE id = :job_id"
            ),
            {"job_id": claimed.id},
        )
    # The heartbeat is stale but the owner still holds the provider lock: leave it alone.
    with owner() as live_recovery:
        assert HarvestRepository(live_recovery).recover_stale(180) == []
    owner_session.close()
    connection.close()
    engine.dispose()

    with owner() as recovery:
        with pytest.raises(OwnershipLost, match="no longer owned"):
            HarvestRepository(recovery).heartbeat(claimed.id)
        with pytest.raises(OwnershipLost, match="not running on this connection"):
            MetadataRepository(recovery).upsert_language(claimed.id, metadata())
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


def test_job_ownership_stays_on_one_backend_for_the_whole_run() -> None:
    """Advisory locks and owner_backend_pid both die if the backend is swapped mid-job."""
    with owner() as session:
        ProviderRepository(session).upsert(provider("scb"))
        claimed_pid = backend_pid(session)
        job_id = start_job(session)
        repository = MetadataRepository(session)
        repository.upsert_language(job_id, metadata())
        assert backend_pid(session) == claimed_pid
        item = HarvestRepository(session).begin_item(job_id, "TAB1")
        HarvestRepository(session).finish_item(job_id, item.id, ItemStatus.UPDATED)
        HarvestRepository(session).finish_job(job_id, JobStatus.COMPLETED)
        assert backend_pid(session) == claimed_pid
        HarvestRepository(session).release_provider("scb")
        assert backend_pid(session) == claimed_pid


def test_no_transaction_is_left_open_between_operations() -> None:
    """A transaction held across an upstream fetch would idle a backend for 30 seconds."""
    with owner() as session:
        providers = ProviderRepository(session)
        queue = HarvestRepository(session)
        repository = MetadataRepository(session)

        providers.upsert(provider("scb"))
        assert not session.in_transaction()

        calls = (
            lambda: providers.get("scb"),
            lambda: providers.list(),
            lambda: providers.set_enabled("scb", True),
            lambda: queue.enqueue("scb", HarvestRequest()),
            lambda: queue.list_jobs(),
            lambda: queue.queue_counts(),
            lambda: queue.claim(),
            lambda: repository.upsert_language(_only_job(queue), metadata()),
            lambda: repository.load_language_state("scb-tab1"),
            lambda: repository.get_language("scb-tab1", "sv"),
            lambda: repository.resolve_id("scb-tab1"),
            lambda: repository.search("Befolkning"),
            lambda: repository.mark_checked(_only_job(queue), "scb-tab1", "sv"),
            lambda: repository.set_operator_disabled("scb-tab1", False),
            lambda: queue.list_items(_only_job(queue)),
            lambda: queue.heartbeat(_only_job(queue)),
            lambda: ScheduleRepository(session).list_schedules(),
            lambda: queue.recover_stale(180),
        )
        for call in calls:
            call()
            assert not session.in_transaction(), call


def _only_job(queue: HarvestRepository) -> int:
    return queue.list_jobs()[0].id


def test_native_identity_is_preserved_on_canonical_collision() -> None:
    with owner() as session:
        ProviderRepository(session).upsert(provider("scb"))
        job_id = start_job(session)
        repository = MetadataRepository(session)
        first = metadata()
        second = metadata().model_copy(update={"native_table_id": "tab1"})
        first_id = repository.upsert_language(job_id, first)
        second_id = repository.upsert_language(job_id, second)
        assert first_id != second_id
        assert repository.upsert_language(job_id, second) == second_id
        assert repository.get_table(first_id).native_table_id == "TAB1"
        assert repository.get_table(second_id).native_table_id == "tab1"


def test_numeric_metadata_round_trip_and_sql_observation_guard() -> None:
    from decimal import Decimal

    from sqlalchemy.exc import IntegrityError

    with owner() as session:
        ProviderRepository(session).upsert(provider("scb"))
        job_id = start_job(session)
        repository = MetadataRepository(session)
        payload = metadata().model_dump()
        payload["metadata"]["dataset"]["dimension"]["region"]["category"]["coordinates"] = {
            "01": [Decimal("18.1234567890123456789"), Decimal("59.0")]
        }
        result = MetadataFetchResult.model_validate(payload)
        repository.upsert_language(job_id, result)
        restored = repository.get_language("scb-tab1", "sv")
        assert restored.dataset.dimensions[0].category.coordinates["01"][0] == Decimal(
            "18.1234567890123456789"
        )
        with pytest.raises(IntegrityError), session.begin():
            session.execute(
                text(
                    "UPDATE table_metadata SET dataset = jsonb_set(dataset, '{value}', '[1,2]'::jsonb)"
                )
            )
        assert repository.get_language("scb-tab1", "sv").dataset.to_mapping()["value"] == []
