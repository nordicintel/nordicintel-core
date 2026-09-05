"""PostgreSQL-backed harvest admission, scheduling, and lifecycle operations."""

from __future__ import annotations

from datetime import datetime

from psycopg.types.json import Jsonb

from nordicintel_core.errors import AdmissionError, OwnershipLost
from nordicintel_core.models import (
    Diagnostic,
    DiagnosticStage,
    HarvestItem,
    HarvestJob,
    HarvestRequest,
    HarvestSchedule,
    ItemStatus,
    JobStatus,
    JobTrigger,
    QueueCount,
)

from ._typing import Connection, Row, page
from .sql_files import read_query


def _diagnostic(value: Diagnostic | None) -> Jsonb | None:
    return None if value is None else Jsonb(value.model_dump(mode="json"))


def _job(row: Row) -> HarvestJob:
    data = dict(row)
    data.pop("owner_backend_pid", None)
    return HarvestJob.model_validate(data)


def _item(row: Row) -> HarvestItem:
    data = dict(row)
    data["table_id"] = data.pop("dataset_id", None)
    return HarvestItem.model_validate(data)


class HarvestRepository:
    """Operations whose transaction and lock scopes form the harvest queue contract."""

    def __init__(self, connection: Connection) -> None:
        self.connection = connection

    def enqueue(
        self,
        provider_id: str,
        request: HarvestRequest,
        *,
        trigger: JobTrigger = JobTrigger.MANUAL,
        request_key: str | None = None,
    ) -> HarvestJob:
        if request_key is not None and not 1 <= len(request_key) <= 200:
            raise AdmissionError(422, "Idempotency key must contain 1 to 200 characters")
        request_json = request.model_dump(mode="json")
        with self.connection.transaction():
            provider = self.connection.execute(
                read_query("provider_admission.sql"), (provider_id,)
            ).fetchone()
            if provider is None:
                raise AdmissionError(404, "Provider does not exist")
            if not provider["enabled"]:
                raise AdmissionError(409, "Provider is disabled")
            if request.table_id is not None:
                owner = self.connection.execute(
                    read_query("dataset_provider.sql"), (request.table_id,)
                ).fetchone()
                if owner is None or owner["provider_id"] != provider_id:
                    raise AdmissionError(422, "Table does not belong to this provider")
            row = self.connection.execute(
                read_query("job_enqueue.sql"),
                (provider_id, Jsonb(request_json), trigger.value, request_key),
            ).fetchone()
            if row is None:
                row = self.connection.execute(
                    read_query("job_by_key.sql"), (request_key,)
                ).fetchone()
                if row is None:
                    raise RuntimeError("Conflicting idempotency row disappeared")
                if row["provider_id"] != provider_id or row["request"] != request_json:
                    raise AdmissionError(409, "Idempotency key belongs to another request")
        return _job(row)

    def get_job(self, job_id: int) -> HarvestJob | None:
        row = self.connection.execute(read_query("job_get.sql"), (job_id,)).fetchone()
        return None if row is None else _job(row)

    def list_jobs(
        self,
        *,
        provider_id: str | None = None,
        status: JobStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[HarvestJob]:
        limit, offset = page(limit, offset)
        status_value = None if status is None else status.value
        rows = self.connection.execute(
            read_query("job_list.sql"),
            (provider_id, provider_id, status_value, status_value, limit, offset),
        ).fetchall()
        return [_job(row) for row in rows]

    def queue_counts(self) -> list[QueueCount]:
        rows = self.connection.execute(read_query("queue_counts.sql")).fetchall()
        return [QueueCount.model_validate(row) for row in rows]

    def claim(self) -> HarvestJob | None:
        excluded: list[str] = []
        while True:
            with self.connection.transaction():
                row = self.connection.execute(
                    read_query("job_claim_candidates.sql"), (excluded,)
                ).fetchone()
                if row is None:
                    return None
                provider_id = str(row["provider_id"])
                lock = self.connection.execute(
                    read_query("provider_try_lock.sql"), (provider_id,)
                ).fetchone()
                if not lock["acquired"]:
                    excluded.append(provider_id)
                    continue
                claimed = self.connection.execute(
                    read_query("job_mark_running.sql"), (row["id"],)
                ).fetchone()
                if claimed is None:
                    self.connection.execute(read_query("provider_unlock.sql"), (provider_id,))
                    continue
                return _job(claimed)

    def release_provider(self, provider_id: str) -> None:
        row = self.connection.execute(
            read_query("provider_unlock.sql"), (provider_id,)
        ).fetchone()
        if row is None or not row["released"]:
            raise OwnershipLost("Provider lock is not owned by this connection")

    def heartbeat(self, job_id: int) -> bool:
        row = self.connection.execute(read_query("job_heartbeat.sql"), (job_id,)).fetchone()
        if row is None:
            raise OwnershipLost("Running job is no longer owned")
        return bool(row["stop_requested"])

    def cancel(self, job_id: int) -> HarvestJob:
        with self.connection.transaction():
            row = self.connection.execute(
                read_query("job_cancel_lock.sql"), (job_id,)
            ).fetchone()
            if row is None:
                raise AdmissionError(404, "Job does not exist")
            if row["status"] == JobStatus.QUEUED.value:
                row = self.connection.execute(
                    read_query("job_cancel_queued.sql"), (job_id,)
                ).fetchone()
            elif row["status"] == JobStatus.RUNNING.value:
                row = self.connection.execute(
                    read_query("job_cancel_running.sql"), (job_id,)
                ).fetchone()
        return _job(row)

    def begin_item(
        self, job_id: int, source_table_id: str, *, table_id: str | None = None
    ) -> HarvestItem:
        if not source_table_id.strip():
            raise ValueError("source_table_id must not be blank")
        with self.connection.transaction():
            row = self.connection.execute(
                read_query("item_begin.sql"),
                (job_id, source_table_id, table_id, job_id, table_id, table_id),
            ).fetchone()
        if row is None:
            raise OwnershipLost("Job is not running")
        return _item(row)

    def finish_item(
        self,
        job_id: int,
        item_id: int,
        status: ItemStatus,
        *,
        error: Diagnostic | None = None,
        table_id: str | None = None,
    ) -> HarvestItem:
        if status is ItemStatus.RUNNING:
            raise ValueError("finish_item requires a terminal item status")
        if (status is ItemStatus.FAILED) != (error is not None):
            raise ValueError("only failed items carry a diagnostic")
        with self.connection.transaction():
            row = self.connection.execute(
                read_query("item_finish.sql"),
                (
                    status.value,
                    _diagnostic(error),
                    table_id,
                    item_id,
                    job_id,
                    table_id,
                    table_id,
                ),
            ).fetchone()
        if row is None:
            raise OwnershipLost("Item or job is no longer running")
        return _item(row)

    def list_items(
        self,
        job_id: int,
        *,
        status: ItemStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[HarvestItem]:
        limit, offset = page(limit, offset)
        status_value = None if status is None else status.value
        rows = self.connection.execute(
            read_query("item_list.sql"),
            (job_id, status_value, status_value, limit, offset),
        ).fetchall()
        return [_item(row) for row in rows]

    def finish_job(
        self, job_id: int, status: JobStatus, *, error: Diagnostic | None = None
    ) -> HarvestJob:
        if status not in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}:
            raise ValueError("finish_job requires a terminal job status")
        if (status is JobStatus.FAILED) != (error is not None):
            raise ValueError("only failed jobs carry a diagnostic")
        with self.connection.transaction():
            current = self.connection.execute(
                read_query("job_finish_lock.sql"), (job_id,)
            ).fetchone()
            if current is None or current["status"] != JobStatus.RUNNING.value:
                raise OwnershipLost("Job is no longer running")
            if bool(current["cancel_requested"]) != (status is JobStatus.CANCELLED):
                raise ValueError("cancelled jobs require an observed cancellation request")
            unfinished = self.connection.execute(
                read_query("item_running_exists.sql"), (job_id,)
            ).fetchone()
            if unfinished is not None:
                if status is not JobStatus.FAILED or error is None:
                    raise ValueError("job has unfinished items")
                self.connection.execute(
                    read_query("item_fail_running.sql"), (_diagnostic(error), job_id)
                )
            row = self.connection.execute(
                read_query("job_finish.sql"), (status.value, _diagnostic(error), job_id)
            ).fetchone()
        return _job(row)

    def recover_stale(self, stale_after_seconds: int, *, limit: int = 100) -> list[int]:
        if stale_after_seconds <= 0:
            raise ValueError("stale_after_seconds must be positive")
        limit, _ = page(limit, 0)
        candidates = self.connection.execute(
            read_query("job_stale.sql"), (stale_after_seconds, limit)
        ).fetchall()
        recovered: list[int] = []
        for candidate in candidates:
            provider_id = str(candidate["provider_id"])
            lock = self.connection.execute(
                read_query("provider_try_lock.sql"), (provider_id,)
            ).fetchone()
            if not lock["acquired"]:
                continue
            try:
                diagnostic = Diagnostic(
                    code="worker_abandoned",
                    message="The worker session ended before the job completed.",
                    stage=DiagnosticStage.INTERRUPTED,
                )
                with self.connection.transaction():
                    current = self.connection.execute(
                        read_query("job_recover_lock.sql"),
                        (candidate["id"], stale_after_seconds),
                    ).fetchone()
                    if current is None:
                        continue
                    self.connection.execute(
                        read_query("item_fail_running.sql"),
                        (_diagnostic(diagnostic), candidate["id"]),
                    )
                    self.connection.execute(
                        read_query("job_finish.sql"),
                        (JobStatus.FAILED.value, _diagnostic(diagnostic), candidate["id"]),
                    )
                    recovered.append(int(candidate["id"]))
            finally:
                self.connection.execute(read_query("provider_unlock.sql"), (provider_id,))
        return recovered


class ScheduleRepository:
    def __init__(self, connection: Connection) -> None:
        self.connection = connection

    def try_singleton_lock(self) -> bool:
        row = self.connection.execute(read_query("scheduler_try_lock.sql")).fetchone()
        return bool(row["acquired"])

    def release_singleton_lock(self) -> None:
        row = self.connection.execute(read_query("scheduler_unlock.sql")).fetchone()
        if row is None or not row["released"]:
            raise OwnershipLost("Scheduler lock is not owned by this connection")

    def get(self, provider_id: str) -> HarvestSchedule | None:
        row = self.connection.execute(
            read_query("schedule_get.sql"), (provider_id,)
        ).fetchone()
        return None if row is None else HarvestSchedule.model_validate(row)

    def upsert(
        self,
        provider_id: str,
        *,
        enabled: bool,
        every_seconds: int,
        next_run_at: datetime,
        request: HarvestRequest,
    ) -> HarvestSchedule:
        if every_seconds <= 0:
            raise ValueError("every_seconds must be positive")
        if request.table_id is not None:
            raise ValueError("scheduled requests must be provider-wide")
        with self.connection.transaction():
            row = self.connection.execute(
                read_query("schedule_upsert.sql"),
                (
                    provider_id,
                    enabled,
                    every_seconds,
                    next_run_at,
                    Jsonb(request.model_dump(mode="json")),
                ),
            ).fetchone()
        return HarvestSchedule.model_validate(row)

    def list_schedules(self, *, limit: int = 50, offset: int = 0) -> list[HarvestSchedule]:
        limit, offset = page(limit, offset)
        rows = self.connection.execute(
            read_query("schedule_list.sql"), (limit, offset)
        ).fetchall()
        return [HarvestSchedule.model_validate(row) for row in rows]

    def enqueue_due(self, *, limit: int = 100) -> list[HarvestJob]:
        limit, _ = page(limit, 0)
        jobs: list[HarvestJob] = []
        with self.connection.transaction():
            schedules = self.connection.execute(
                read_query("schedule_due.sql"), (limit,)
            ).fetchall()
            for schedule in schedules:
                active = self.connection.execute(
                    read_query("job_active_provider.sql"), (schedule["provider_id"],)
                ).fetchone()
                if active is None:
                    row = self.connection.execute(
                        read_query("job_enqueue.sql"),
                        (
                            schedule["provider_id"],
                            Jsonb(schedule["request"]),
                            JobTrigger.SCHEDULE.value,
                            None,
                        ),
                    ).fetchone()
                    jobs.append(_job(row))
                self.connection.execute(
                    read_query("schedule_advance.sql"), (schedule["provider_id"],)
                )
        return jobs
