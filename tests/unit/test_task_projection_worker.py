from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from qq_time_agent.adapters.inbound.workers.runner import (
    PermanentJobError,
    RetryableJobError,
)
from qq_time_agent.adapters.inbound.workers.task_projection import (
    DELTA_JOB,
    RECONCILE_JOB,
    UPSERT_JOB,
    AgendaProjectionOutboxRelay,
    AgendaProjectionReconciliationScheduler,
    TaskCompletionDeltaScheduler,
    TaskProjectionJobHandler,
)
from qq_time_agent.contracts.events import EventEnvelope
from qq_time_agent.contracts.jobs import JobLease, JobRequest
from qq_time_agent.modules.agenda.contracts import AgendaEntryView
from qq_time_agent.modules.task_projection.application import ProjectionOperationError
from qq_time_agent.modules.task_projection.contracts import ProjectionResult
from qq_time_agent.modules.task_projection.domain import TaskProjectionTarget

NOW = datetime(2026, 9, 13, 8, tzinfo=UTC)


@dataclass
class Clock:
    def now(self) -> datetime:
        return NOW


@dataclass
class Outbox:
    event: EventEnvelope
    published: list[UUID] = field(default_factory=list)

    async def unpublished_for_types(
        self, event_types: tuple[str, ...], limit: int
    ) -> list[EventEnvelope]:
        return [self.event]

    async def mark_published(self, event_id: UUID, published_at: datetime) -> None:
        self.published.append(event_id)


@dataclass
class Queue:
    requests: list[JobRequest] = field(default_factory=list)

    async def enqueue(self, request: JobRequest) -> UUID:
        self.requests.append(request)
        return uuid4()


@dataclass
class Agenda:
    entries: tuple[AgendaEntryView, ...]

    async def list_active_page(
        self, after_entry_id: UUID | None, limit: int
    ) -> tuple[AgendaEntryView, ...]:
        if after_entry_id is not None:
            return ()
        return self.entries[:limit]


@dataclass
class Projections:
    failure_class: str | None = None

    async def project_agenda_entry(
        self, entry_id: UUID, expected_version: int, idempotency_key: str
    ) -> ProjectionResult:
        if self.failure_class is not None:
            raise ProjectionOperationError(self.failure_class)
        return ProjectionResult(entry_id, expected_version, "PROJECTED", 1)


@dataclass
class Targets:
    target: TaskProjectionTarget

    async def list_ready(self, user_id: str) -> tuple[TaskProjectionTarget, ...]:
        return (self.target,) if user_id == self.target.user_id else ()


def _entry() -> AgendaEntryView:
    return AgendaEntryView(
        uuid4(),
        "TASK_BLOCK",
        "测评",
        NOW,
        NOW,
        "Asia/Shanghai",
        "ACTIVE",
        (),
        uuid4(),
        1,
    )


@pytest.mark.asyncio
async def test_outbox_is_marked_only_after_projection_job_is_enqueued() -> None:
    entry_id, event_id = uuid4(), uuid4()
    event = EventEnvelope(
        event_id,
        "agenda.entry.changed",
        1,
        f"agenda:{entry_id}",
        {
            "agenda_entry_id": str(entry_id),
            "agenda_entry_version": 2,
            "status": "ACTIVE",
        },
        NOW,
    )
    outbox, queue = Outbox(event), Queue()

    count = await AgendaProjectionOutboxRelay(outbox, queue, Clock()).enqueue_due()

    assert count == 1 and outbox.published == [event_id]
    assert queue.requests[0].kind == UPSERT_JOB
    assert queue.requests[0].payload["agenda_entry_version"] == 2


@pytest.mark.asyncio
async def test_reconciliation_backfills_active_entries_once_per_time_bucket() -> None:
    entry, queue = _entry(), Queue()
    scheduler = AgendaProjectionReconciliationScheduler(Agenda((entry,)), queue, Clock())

    assert await scheduler.enqueue_due() == 1
    assert await scheduler.enqueue_due() == 0
    assert queue.requests[0].kind == RECONCILE_JOB
    assert str(entry.agenda_entry_id) in queue.requests[0].idempotency_key


@pytest.mark.asyncio
async def test_delta_scheduler_enqueues_each_ready_target_once_per_minute() -> None:
    target = TaskProjectionTarget.resolve("owner", uuid4(), "managed", "小智建议", NOW)
    queue = Queue()
    scheduler = TaskCompletionDeltaScheduler(Targets(target), queue, Clock())

    assert await scheduler.enqueue_due() == 1
    assert await scheduler.enqueue_due() == 0
    assert queue.requests[0].kind == DELTA_JOB
    assert queue.requests[0].payload == {"connection_id": str(target.connection_id)}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure_class", "error"),
    [
        ("TransientProvider", RetryableJobError),
        ("PermanentProvider", PermanentJobError),
    ],
)
async def test_job_handler_preserves_retry_classification(
    failure_class: str, error: type[RuntimeError]
) -> None:
    entry_id = uuid4()
    lease = JobLease(
        uuid4(),
        UPSERT_JOB,
        {"agenda_entry_id": str(entry_id), "agenda_entry_version": 1},
        "worker",
        1,
        5,
    )
    with pytest.raises(error, match=failure_class):
        await TaskProjectionJobHandler(Projections(failure_class))(lease)
