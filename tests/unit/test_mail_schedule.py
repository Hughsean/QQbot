from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from qq_time_agent.adapters.inbound.workers.mail_schedule import PeriodicMailSyncScheduler
from qq_time_agent.contracts.jobs import JobLease, JobRequest, JobStatusView
from qq_time_agent.modules.connections.contracts import ConnectionStatusView


@dataclass
class FixedClock:
    value: datetime = datetime(2026, 8, 13, tzinfo=UTC)

    def now(self) -> datetime:
        return self.value


@dataclass
class FakeConnections:
    view: ConnectionStatusView | None

    async def status(self, user_id: str) -> ConnectionStatusView | None:
        assert user_id == "owner"
        return self.view


@dataclass
class MemoryQueue:
    requests: dict[str, JobRequest] = field(default_factory=dict)

    async def enqueue(self, request: JobRequest) -> UUID:
        self.requests.setdefault(request.idempotency_key, request)
        return uuid4()

    async def status(self, job_id: UUID) -> JobStatusView | None:
        return None

    async def lease_due(
        self, now: datetime, worker_id: str, limit: int, lease_duration: timedelta
    ) -> list[JobLease]:
        return []

    async def complete(self, lease: JobLease, now: datetime) -> None:
        return None

    async def fail(
        self,
        lease: JobLease,
        now: datetime,
        failure_class: str,
        retry_at: datetime | None,
    ) -> None:
        return None


def _view(status: str) -> ConnectionStatusView:
    return ConnectionStatusView(
        uuid4(), "MICROSOFT", status, ("Mail.Read",), "o***@example.test", None
    )


@pytest.mark.asyncio
async def test_periodic_scheduler_enqueues_once_per_interval() -> None:
    clock = FixedClock()
    queue = MemoryQueue()
    scheduler = PeriodicMailSyncScheduler(FakeConnections(_view("ACTIVE")), queue, clock, 300)
    await scheduler.enqueue_due()
    await scheduler.enqueue_due()
    assert len(queue.requests) == 1
    clock.value += timedelta(minutes=5)
    await scheduler.enqueue_due()
    assert len(queue.requests) == 2


@pytest.mark.asyncio
async def test_periodic_scheduler_skips_unavailable_connection() -> None:
    queue = MemoryQueue()
    scheduler = PeriodicMailSyncScheduler(
        FakeConnections(_view("DISCONNECTED")), queue, FixedClock(), 300
    )
    await scheduler.enqueue_due()
    assert queue.requests == {}


def test_periodic_scheduler_rejects_too_small_interval() -> None:
    with pytest.raises(ValueError, match="at least 60"):
        PeriodicMailSyncScheduler(FakeConnections(None), MemoryQueue(), FixedClock(), 30)
