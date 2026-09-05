"""PostgreSQL-backed harvest admission, scheduling, and lifecycle operations.

The statements here are written out rather than left to the ORM because their lock scope
*is* the queue contract: which rows are locked, which are skipped, and which physical
backend is allowed to advance a job. Every public method is one short transaction, so no
transaction is ever left open while a worker waits on an upstream request.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, exists, func, insert, literal, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, aliased

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

from ._typing import page
from .schema import HarvestItem as ItemRow
from .schema import HarvestJob as JobRow
from .schema import HarvestSchedule as ScheduleRow
from .schema import Provider, TableRecord

# One convention, shared by every worker and by recovery. If it changed between releases,
# two processes could each believe they own a provider, so it is deployment state.
_LOCK_SALT = 0
_SCHEDULER_LOCK_KEY = "nordicintel:scheduler"

_ACTIVE_STATUSES = (JobStatus.QUEUED.value, JobStatus.RUNNING.value)


def _seconds(count: Any) -> ColumnElement[Any]:
    """Seconds as an interval.

    ``make_interval`` takes (years, months, weeks, days, hours, mins, secs) positionally;
    everything before ``secs`` is zero.
    """
    return func.make_interval(0, 0, 0, 0, 0, 0, count)


def _lock_key(name: str) -> ColumnElement[int]:
    return func.hashtextextended(name, _LOCK_SALT)


def _diagnostic(value: Diagnostic | None) -> dict[str, Any] | None:
    return None if value is None else value.model_dump(mode="json")


def _job(row: JobRow) -> HarvestJob:
    """Project a job row; ``owner_backend_pid`` is internal ownership state."""
    return HarvestJob(
        id=row.id,
        provider_id=row.provider_id,
        request=HarvestRequest.model_validate(row.request),
        trigger=JobTrigger(row.trigger),
        status=JobStatus(row.status),
        request_key=row.request_key,
        cancel_requested=row.cancel_requested,
        created_at=row.created_at,
        started_at=row.started_at,
        heartbeat_at=row.heartbeat_at,
        finished_at=row.finished_at,
        error=None if row.error is None else Diagnostic.model_validate(row.error),
    )


def _item(row: ItemRow) -> HarvestItem:
    return HarvestItem(
        id=row.id,
        job_id=row.job_id,
        source_table_id=row.source_table_id,
        table_id=row.dataset_id,
        status=ItemStatus(row.status),
        started_at=row.started_at,
        finished_at=row.finished_at,
        error=None if row.error is None else Diagnostic.model_validate(row.error),
    )


def _schedule(row: ScheduleRow) -> HarvestSchedule:
    return HarvestSchedule(
        provider_id=row.provider_id,
        enabled=row.enabled,
        every_seconds=row.every_seconds,
        next_run_at=row.next_run_at,
        request=HarvestRequest.model_validate(row.request),
    )


def _owned(job_id: int) -> ColumnElement[bool]:
    """Only the backend that claimed a running job may advance it."""
    return (
        (JobRow.id == job_id)
        & (JobRow.status == JobStatus.RUNNING.value)
        & (JobRow.owner_backend_pid == func.pg_backend_pid())
    )


def _table_belongs_to_job(table_id: str | None) -> ColumnElement[bool]:
    """A named table must belong to the job's own provider, or not be named at all."""
    if table_id is None:
        return literal(True)
    return exists(
        select(literal(1))
        .select_from(TableRecord)
        .where(TableRecord.id == table_id, TableRecord.provider_id == JobRow.provider_id)
    )


class HarvestRepository:
    """Operations whose transaction and lock scopes form the harvest queue contract."""

    def __init__(self, session: Session) -> None:
        self.session = session

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
        with self.session.begin():
            provider = self.session.execute(
                select(Provider.id, Provider.enabled)
                .where(Provider.id == provider_id)
                .with_for_update()
            ).one_or_none()
            if provider is None:
                raise AdmissionError(404, "Provider does not exist")
            if not provider.enabled:
                raise AdmissionError(409, "Provider is disabled")
            if request.table_id is not None:
                owner = self.session.scalar(
                    select(TableRecord.provider_id).where(TableRecord.id == request.table_id)
                )
                if owner != provider_id:
                    raise AdmissionError(422, "Table does not belong to this provider")
            row = self.session.scalars(
                pg_insert(JobRow)
                .values(
                    provider_id=provider_id,
                    request=request_json,
                    trigger=trigger.value,
                    request_key=request_key,
                )
                .on_conflict_do_nothing(index_elements=[JobRow.request_key])
                .returning(JobRow)
            ).one_or_none()
            if row is None:
                row = self.session.scalars(
                    select(JobRow).where(JobRow.request_key == request_key)
                ).one_or_none()
                if row is None:
                    raise RuntimeError("Conflicting idempotency row disappeared")
                if row.provider_id != provider_id or row.request != request_json:
                    raise AdmissionError(409, "Idempotency key belongs to another request")
            return _job(row)

    def get_job(self, job_id: int) -> HarvestJob | None:
        with self.session.begin():
            row = self.session.get(JobRow, job_id)
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
        statement = select(JobRow)
        if provider_id is not None:
            statement = statement.where(JobRow.provider_id == provider_id)
        if status is not None:
            statement = statement.where(JobRow.status == status.value)
        statement = (
            statement.order_by(JobRow.created_at.desc(), JobRow.id.desc())
            .limit(limit)
            .offset(offset)
        )
        with self.session.begin():
            return [_job(row) for row in self.session.scalars(statement)]

    def queue_counts(self) -> list[QueueCount]:
        statement = (
            select(JobRow.provider_id, JobRow.status, func.count().label("total"))
            .where(JobRow.status.in_(_ACTIVE_STATUSES))
            .group_by(JobRow.provider_id, JobRow.status)
            .order_by(JobRow.provider_id, JobRow.status)
        )
        with self.session.begin():
            return [
                QueueCount(
                    provider_id=row.provider_id,
                    status=JobStatus(row.status),
                    count=row.total,
                )
                for row in self.session.execute(statement)
            ]

    def claim(self) -> HarvestJob | None:
        """Take the oldest eligible job and hold its provider lock for the whole run.

        ``SKIP LOCKED`` only keeps competing workers off the same row for the length of
        this transaction. The provider advisory lock is what serializes the execution that
        follows, and it is session-scoped: outliving this commit is the point.
        """
        active = aliased(JobRow, name="active")
        excluded: list[str] = []
        while True:
            with self.session.begin():
                candidate = self.session.scalars(
                    select(JobRow)
                    .join(Provider, Provider.id == JobRow.provider_id)
                    .where(
                        JobRow.status == JobStatus.QUEUED.value,
                        Provider.enabled,
                        JobRow.provider_id.not_in(excluded),
                        ~exists(
                            select(literal(1))
                            .select_from(active)
                            .where(
                                active.provider_id == JobRow.provider_id,
                                active.status == JobStatus.RUNNING.value,
                            )
                        ),
                    )
                    .order_by(JobRow.created_at, JobRow.id)
                    .limit(1)
                    .with_for_update(of=JobRow, skip_locked=True)
                ).one_or_none()
                if candidate is None:
                    return None
                provider_id = candidate.provider_id
                acquired = self.session.scalar(
                    select(func.pg_try_advisory_lock(_lock_key(provider_id)))
                )
                if not acquired:
                    excluded.append(provider_id)
                    continue
                claimed = self.session.scalars(
                    update(JobRow)
                    .where(JobRow.id == candidate.id, JobRow.status == JobStatus.QUEUED.value)
                    .values(
                        status=JobStatus.RUNNING.value,
                        started_at=func.now(),
                        heartbeat_at=func.now(),
                        owner_backend_pid=func.pg_backend_pid(),
                    )
                    .returning(JobRow)
                ).one_or_none()
                if claimed is None:
                    self.session.scalar(select(func.pg_advisory_unlock(_lock_key(provider_id))))
                    continue
                return _job(claimed)

    def release_provider(self, provider_id: str) -> None:
        with self.session.begin():
            released = self.session.scalar(select(func.pg_advisory_unlock(_lock_key(provider_id))))
        if not released:
            raise OwnershipLost("Provider lock is not owned by this connection")

    def heartbeat(self, job_id: int) -> bool:
        """Refresh the liveness stamp; a disabled provider reads as a stop request."""
        with self.session.begin():
            row = self.session.execute(
                update(JobRow)
                .where(_owned(job_id), Provider.id == JobRow.provider_id)
                .values(
                    heartbeat_at=func.now(),
                    cancel_requested=or_(JobRow.cancel_requested, ~Provider.enabled),
                )
                .returning(JobRow.cancel_requested)
            ).one_or_none()
            if row is None:
                raise OwnershipLost("Running job is no longer owned")
            return bool(row.cancel_requested)

    def cancel(self, job_id: int) -> HarvestJob:
        """Cancel queued work outright; ask running work to stop cooperatively."""
        with self.session.begin():
            current = self.session.scalars(
                select(JobRow).where(JobRow.id == job_id).with_for_update()
            ).one_or_none()
            if current is None:
                raise AdmissionError(404, "Job does not exist")
            if current.status == JobStatus.QUEUED.value:
                current.status = JobStatus.CANCELLED.value
                current.finished_at = func.now()
            elif current.status == JobStatus.RUNNING.value:
                current.cancel_requested = True
            self.session.flush()
            self.session.refresh(current)
            return _job(current)

    def begin_item(
        self, job_id: int, source_table_id: str, *, table_id: str | None = None
    ) -> HarvestItem:
        if not source_table_id.strip():
            raise ValueError("source_table_id must not be blank")
        source = (
            select(
                literal(job_id),
                literal(source_table_id),
                literal(table_id, type_=ItemRow.dataset_id.type),
            )
            .select_from(JobRow)
            .where(_owned(job_id), _table_belongs_to_job(table_id))
        )
        with self.session.begin():
            row = self.session.scalars(
                insert(ItemRow)
                .from_select(["job_id", "source_table_id", "dataset_id"], source)
                .returning(ItemRow)
            ).one_or_none()
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
        with self.session.begin():
            row = self.session.scalars(
                update(ItemRow)
                .where(
                    ItemRow.id == item_id,
                    ItemRow.job_id == job_id,
                    ItemRow.status == ItemStatus.RUNNING.value,
                    JobRow.id == ItemRow.job_id,
                    _owned(job_id),
                    _table_belongs_to_job(table_id),
                )
                .values(
                    status=status.value,
                    finished_at=func.now(),
                    error=_diagnostic(error),
                    dataset_id=func.coalesce(
                        literal(table_id, type_=ItemRow.dataset_id.type), ItemRow.dataset_id
                    ),
                )
                .returning(ItemRow)
            ).one_or_none()
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
        statement = select(ItemRow).where(ItemRow.job_id == job_id)
        if status is not None:
            statement = statement.where(ItemRow.status == status.value)
        statement = statement.order_by(ItemRow.id).limit(limit).offset(offset)
        with self.session.begin():
            return [_item(row) for row in self.session.scalars(statement)]

    def finish_job(
        self, job_id: int, status: JobStatus, *, error: Diagnostic | None = None
    ) -> HarvestJob:
        if status not in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}:
            raise ValueError("finish_job requires a terminal job status")
        if (status is JobStatus.FAILED) != (error is not None):
            raise ValueError("only failed jobs carry a diagnostic")
        with self.session.begin():
            current = self.session.scalars(
                select(JobRow)
                .where(JobRow.id == job_id, JobRow.owner_backend_pid == func.pg_backend_pid())
                .with_for_update()
            ).one_or_none()
            if current is None or current.status != JobStatus.RUNNING.value:
                raise OwnershipLost("Job is no longer running")
            if bool(current.cancel_requested) != (status is JobStatus.CANCELLED):
                raise ValueError("cancelled jobs require an observed cancellation request")
            unfinished = self.session.scalar(
                select(literal(1))
                .select_from(ItemRow)
                .where(ItemRow.job_id == job_id, ItemRow.status == ItemStatus.RUNNING.value)
                .limit(1)
            )
            if unfinished is not None:
                if status is not JobStatus.FAILED or error is None:
                    raise ValueError("job has unfinished items")
                self._fail_running_items(job_id, error)
            current.status = status.value
            current.finished_at = func.now()
            current.error = _diagnostic(error)
            current.owner_backend_pid = None
            self.session.flush()
            self.session.refresh(current)
            return _job(current)

    def _fail_running_items(self, job_id: int, error: Diagnostic) -> None:
        self.session.execute(
            update(ItemRow)
            .where(ItemRow.job_id == job_id, ItemRow.status == ItemStatus.RUNNING.value)
            .values(
                status=ItemStatus.FAILED.value,
                finished_at=func.now(),
                error=_diagnostic(error),
            )
        )

    def recover_stale(self, stale_after_seconds: int, *, limit: int = 100) -> list[int]:
        """Close jobs whose worker stopped reporting, but only if nobody still owns them.

        A stale heartbeat is a suspicion, not proof. The provider lock being free is the
        evidence: if it is still held the owning worker is alive, and the job is left alone.
        """
        if stale_after_seconds <= 0:
            raise ValueError("stale_after_seconds must be positive")
        limit, _ = page(limit, 0)
        stale = JobRow.heartbeat_at < func.now() - _seconds(stale_after_seconds)
        with self.session.begin():
            candidates = self.session.execute(
                select(JobRow.id, JobRow.provider_id)
                .where(JobRow.status == JobStatus.RUNNING.value, stale)
                .order_by(JobRow.heartbeat_at, JobRow.id)
                .limit(limit)
            ).all()
        diagnostic = Diagnostic(
            code="worker_abandoned",
            message="The worker session ended before the job completed.",
            stage=DiagnosticStage.INTERRUPTED,
        )
        recovered: list[int] = []
        for candidate in candidates:
            with self.session.begin():
                acquired = self.session.scalar(
                    select(func.pg_try_advisory_lock(_lock_key(candidate.provider_id)))
                )
            if not acquired:
                continue
            try:
                with self.session.begin():
                    current = self.session.scalars(
                        select(JobRow)
                        .where(
                            JobRow.id == candidate.id,
                            JobRow.status == JobStatus.RUNNING.value,
                            stale,
                        )
                        .with_for_update()
                    ).one_or_none()
                    if current is None:
                        continue
                    self._fail_running_items(candidate.id, diagnostic)
                    current.status = JobStatus.FAILED.value
                    current.finished_at = func.now()
                    current.error = _diagnostic(diagnostic)
                    current.owner_backend_pid = None
                    recovered.append(candidate.id)
            finally:
                with self.session.begin():
                    self.session.scalar(
                        select(func.pg_advisory_unlock(_lock_key(candidate.provider_id)))
                    )
        return recovered


class ScheduleRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def try_singleton_lock(self) -> bool:
        with self.session.begin():
            return bool(
                self.session.scalar(
                    select(func.pg_try_advisory_lock(_lock_key(_SCHEDULER_LOCK_KEY)))
                )
            )

    def release_singleton_lock(self) -> None:
        with self.session.begin():
            released = self.session.scalar(
                select(func.pg_advisory_unlock(_lock_key(_SCHEDULER_LOCK_KEY)))
            )
        if not released:
            raise OwnershipLost("Scheduler lock is not owned by this connection")

    def get(self, provider_id: str) -> HarvestSchedule | None:
        with self.session.begin():
            row = self.session.get(ScheduleRow, provider_id)
            return None if row is None else _schedule(row)

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
        values: dict[str, Any] = {
            "provider_id": provider_id,
            "enabled": enabled,
            "every_seconds": every_seconds,
            "next_run_at": next_run_at,
            "request": request.model_dump(mode="json"),
        }
        statement = (
            pg_insert(ScheduleRow)
            .values(**values)
            .on_conflict_do_update(
                index_elements=[ScheduleRow.provider_id],
                set_={name: value for name, value in values.items() if name != "provider_id"},
            )
            .returning(ScheduleRow)
        )
        with self.session.begin():
            return _schedule(self.session.scalars(statement).one())

    def list_schedules(self, *, limit: int = 50, offset: int = 0) -> list[HarvestSchedule]:
        limit, offset = page(limit, offset)
        statement = (
            select(ScheduleRow)
            .order_by(ScheduleRow.next_run_at, ScheduleRow.provider_id)
            .limit(limit)
            .offset(offset)
        )
        with self.session.begin():
            return [_schedule(row) for row in self.session.scalars(statement)]

    def enqueue_due(self, *, limit: int = 100) -> list[HarvestJob]:
        """Enqueue one job per idle due provider and advance every due schedule.

        A busy provider keeps its turn without accumulating one job per missed tick.
        """
        limit, _ = page(limit, 0)
        jobs: list[HarvestJob] = []
        with self.session.begin():
            due = self.session.scalars(
                select(ScheduleRow)
                .join(Provider, Provider.id == ScheduleRow.provider_id)
                .where(
                    ScheduleRow.enabled,
                    Provider.enabled,
                    ScheduleRow.next_run_at <= func.now(),
                )
                .order_by(ScheduleRow.next_run_at, ScheduleRow.provider_id)
                .limit(limit)
                .with_for_update(of=ScheduleRow, skip_locked=True)
            ).all()
            for schedule in due:
                active = self.session.scalar(
                    select(literal(1))
                    .select_from(JobRow)
                    .where(
                        JobRow.provider_id == schedule.provider_id,
                        JobRow.status.in_(_ACTIVE_STATUSES),
                    )
                    .limit(1)
                )
                if active is None:
                    row = self.session.scalars(
                        pg_insert(JobRow)
                        .values(
                            provider_id=schedule.provider_id,
                            request=schedule.request,
                            trigger=JobTrigger.SCHEDULE.value,
                            request_key=None,
                        )
                        .returning(JobRow)
                    ).one()
                    jobs.append(_job(row))
                schedule.next_run_at = func.now() + _seconds(schedule.every_seconds)
        return jobs
