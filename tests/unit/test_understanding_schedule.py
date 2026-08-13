from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from qq_time_agent.adapters.inbound.workers.understanding_schedule import (
    UnderstandingScheduler,
)
from qq_time_agent.contracts.jobs import JobLease, JobRequest, JobStatusView


@dataclass
class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 8, 13, tzinfo=UTC)


@dataclass
class Inbox:
    values: tuple[UUID, ...]

    async def list_normalized(self, limit: int) -> tuple[UUID, ...]:
        return self.values[:limit]


@dataclass
class Queue:
    requests: list[JobRequest] = field(default_factory=list)

    async def enqueue(self, request: JobRequest) -> UUID:
        self.requests.append(request)
        return uuid4()

    async def lease_due(
        self, now: datetime, worker_id: str, limit: int, lease_duration: timedelta
    ) -> list[JobLease]:
        return []

    async def complete(self, lease: JobLease, now: datetime) -> None:
        return None

    async def fail(
        self, lease: JobLease, now: datetime, failure_class: str, retry_at: datetime | None
    ) -> None:
        return None

    async def status(self, job_id: UUID) -> JobStatusView | None:
        return None


@pytest.mark.asyncio
async def test_scheduler_enqueues_id_only_stable_jobs() -> None:
    items = (uuid4(), uuid4())
    queue = Queue()
    scheduler = UnderstandingScheduler(Inbox(items), queue, FixedClock())
    await scheduler.enqueue_due()
    assert [request.kind for request in queue.requests] == ["understanding-run"] * 2
    assert [request.payload for request in queue.requests] == [
        {"inbox_item_id": str(items[0])},
        {"inbox_item_id": str(items[1])},
    ]
    assert all("body" not in request.payload for request in queue.requests)
    assert queue.requests[0].idempotency_key.endswith(":v1")
