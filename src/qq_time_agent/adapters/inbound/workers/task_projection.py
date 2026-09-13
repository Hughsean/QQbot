"""Durable Agenda projection relay, reconciliation scheduler and job handler."""

from datetime import datetime, timedelta
from uuid import UUID

from qq_time_agent.adapters.inbound.workers.runner import (
    PermanentJobError,
    RetryableJobError,
)
from qq_time_agent.adapters.outbound.persistence.outbox import SqlOutbox
from qq_time_agent.contracts.clock import Clock
from qq_time_agent.contracts.jobs import JobLease, JobQueue, JobRequest
from qq_time_agent.modules.agenda.contracts import (
    AGENDA_CHANGED_EVENT,
    AgendaProjectionQueryPort,
)
from qq_time_agent.modules.task_projection.application import (
    ProjectionOperationError,
    TaskCompletionSyncError,
)
from qq_time_agent.modules.task_projection.application.ports import (
    TaskProjectionTargetRepository,
)
from qq_time_agent.modules.task_projection.contracts import (
    TaskCompletionSyncPort,
    TaskProjectionCommandPort,
)

UPSERT_JOB = "task-projection-upsert"
CLOSE_JOB = "task-projection-close"
RECONCILE_JOB = "task-projection-reconcile"
DELTA_JOB = "task-projection-delta"
_RETRYABLE = {
    "Authentication",
    "Authorization",
    "ConnectionUnavailable",
    "RateLimit",
    "TransientProvider",
}


class AgendaProjectionOutboxRelay:
    def __init__(self, outbox: SqlOutbox, queue: JobQueue, clock: Clock) -> None:
        self._outbox = outbox
        self._queue = queue
        self._clock = clock

    async def enqueue_due(self, limit: int = 100) -> int:
        events = await self._outbox.unpublished_for_types((AGENDA_CHANGED_EVENT,), limit)
        for event in events:
            entry_id, version, entry_status = _event_values(event.payload)
            kind = UPSERT_JOB if entry_status == "ACTIVE" else CLOSE_JOB
            await self._queue.enqueue(
                JobRequest(
                    kind,
                    {"agenda_entry_id": str(entry_id), "agenda_entry_version": version},
                    f"task-projection-event:{event.event_id}",
                    self._clock.now(),
                    max_attempts=5,
                )
            )
            await self._outbox.mark_published(event.event_id, self._clock.now())
        return len(events)


class AgendaProjectionReconciliationScheduler:
    def __init__(
        self,
        agenda: AgendaProjectionQueryPort,
        queue: JobQueue,
        clock: Clock,
        interval: timedelta = timedelta(minutes=1),
        page_size: int = 100,
        max_pages: int = 10,
    ) -> None:
        self._agenda = agenda
        self._queue = queue
        self._clock = clock
        self._interval = interval
        self._page_size = page_size
        self._max_pages = max_pages
        self._next_due: datetime | None = None

    async def enqueue_due(self) -> int:
        now = self._clock.now()
        if self._next_due is not None and now < self._next_due:
            return 0
        bucket = int(now.timestamp() // self._interval.total_seconds())
        after: UUID | None = None
        enqueued = 0
        for _ in range(self._max_pages):
            page = await self._agenda.list_active_page(after, self._page_size)
            for entry in page:
                await self._queue.enqueue(
                    JobRequest(
                        RECONCILE_JOB,
                        {
                            "agenda_entry_id": str(entry.agenda_entry_id),
                            "agenda_entry_version": entry.version,
                        },
                        f"task-projection-reconcile:{bucket}:{entry.agenda_entry_id}:{entry.version}",
                        now,
                        max_attempts=5,
                    )
                )
            enqueued += len(page)
            if len(page) < self._page_size:
                break
            after = page[-1].agenda_entry_id
        self._next_due = now + self._interval
        return enqueued


class TaskCompletionDeltaScheduler:
    def __init__(
        self,
        targets: TaskProjectionTargetRepository,
        queue: JobQueue,
        clock: Clock,
        interval: timedelta = timedelta(minutes=1),
        owner_id: str = "owner",
    ) -> None:
        self._targets = targets
        self._queue = queue
        self._clock = clock
        self._interval = interval
        self._owner_id = owner_id
        self._next_due: datetime | None = None

    async def enqueue_due(self) -> int:
        now = self._clock.now()
        if self._next_due is not None and now < self._next_due:
            return 0
        bucket = int(now.timestamp() // self._interval.total_seconds())
        targets = await self._targets.list_ready(self._owner_id)
        for target in targets:
            await self._queue.enqueue(
                JobRequest(
                    DELTA_JOB,
                    {"connection_id": str(target.connection_id)},
                    f"task-projection-delta:{bucket}:{target.connection_id}",
                    now,
                    max_attempts=5,
                )
            )
        self._next_due = now + self._interval
        return len(targets)


class TaskProjectionJobHandler:
    def __init__(self, projections: TaskProjectionCommandPort) -> None:
        self._projections = projections

    async def __call__(self, lease: JobLease) -> None:
        try:
            entry_id, version = _job_values(lease.payload)
            await self._projections.project_agenda_entry(
                entry_id, version, f"task-projection-job:{lease.job_id}"
            )
        except ProjectionOperationError as exc:
            if exc.failure_class in _RETRYABLE:
                raise RetryableJobError(exc.failure_class) from exc
            raise PermanentJobError(exc.failure_class) from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise PermanentJobError("PermanentData") from exc


class TaskCompletionJobHandler:
    def __init__(self, completion: TaskCompletionSyncPort) -> None:
        self._completion = completion

    async def __call__(self, lease: JobLease) -> None:
        try:
            raw_connection_id = lease.payload["connection_id"]
            if not isinstance(raw_connection_id, str):
                raise ValueError("task completion job payload is invalid")
            await self._completion.sync_target(UUID(raw_connection_id))
        except TaskCompletionSyncError as exc:
            if exc.failure_class in _RETRYABLE:
                raise RetryableJobError(exc.failure_class) from exc
            raise PermanentJobError(exc.failure_class) from exc
        except (KeyError, ValueError) as exc:
            raise PermanentJobError("PermanentData") from exc


def _event_values(payload: dict[str, object]) -> tuple[UUID, int, str]:
    entry_id, version = _job_values(payload)
    entry_status = payload["status"]
    if entry_status not in {"ACTIVE", "COMPLETED", "CANCELLED"}:
        raise ValueError("Agenda event status is invalid")
    return entry_id, version, str(entry_status)


def _job_values(payload: dict[str, object]) -> tuple[UUID, int]:
    raw_id = payload["agenda_entry_id"]
    raw_version = payload["agenda_entry_version"]
    if not isinstance(raw_id, str) or not isinstance(raw_version, int) or raw_version < 1:
        raise ValueError("task projection job payload is invalid")
    return UUID(raw_id), raw_version
