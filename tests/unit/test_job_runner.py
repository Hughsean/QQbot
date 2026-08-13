from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from qq_time_agent.adapters.inbound.workers.runner import JobRunner, RetryableJobError
from qq_time_agent.contracts.jobs import JobLease, JobRequest


@dataclass
class FixedClock:
    value: datetime

    def now(self) -> datetime:
        return self.value


@dataclass
class MemoryQueue:
    due: list[JobLease]
    completed: list[UUID] = field(default_factory=list)
    failures: list[tuple[UUID, str, datetime | None]] = field(default_factory=list)

    async def enqueue(self, request: JobRequest) -> UUID:
        return uuid4()

    async def lease_due(
        self, now: datetime, worker_id: str, limit: int, lease_duration: timedelta
    ) -> list[JobLease]:
        leased, self.due = self.due[:limit], self.due[limit:]
        return leased

    async def complete(self, lease: JobLease, now: datetime) -> None:
        self.completed.append(lease.job_id)

    async def fail(
        self,
        lease: JobLease,
        now: datetime,
        failure_class: str,
        retry_at: datetime | None,
    ) -> None:
        self.failures.append((lease.job_id, failure_class, retry_at))

    async def status(self, job_id: UUID) -> None:
        return None


@pytest.mark.asyncio
async def test_runner_completes_successful_job() -> None:
    job = JobLease(uuid4(), "ok", {}, "worker", 1, 3)
    queue = MemoryQueue([job])

    async def handle(_: JobLease) -> None:
        return None

    now = datetime(2026, 8, 13, tzinfo=UTC)
    runner = JobRunner(queue, {"ok": handle}, FixedClock(now), "worker")
    assert await runner.run_once() == 1
    assert queue.completed == [job.job_id]


@pytest.mark.asyncio
async def test_runner_schedules_bounded_retry() -> None:
    job = JobLease(uuid4(), "retry", {}, "worker", 1, 3)
    queue = MemoryQueue([job])
    now = datetime(2026, 8, 13, tzinfo=UTC)

    async def handle(_: JobLease) -> None:
        raise RetryableJobError("TransientProvider")

    runner = JobRunner(queue, {"retry": handle}, FixedClock(now), "worker")
    await runner.run_once()
    assert queue.failures == [(job.job_id, "TransientProvider", now + timedelta(seconds=2))]


@pytest.mark.asyncio
async def test_runner_dead_letters_unknown_job_kind() -> None:
    job = JobLease(uuid4(), "unknown", {}, "worker", 1, 3)
    queue = MemoryQueue([job])
    now = datetime(2026, 8, 13, tzinfo=UTC)
    runner = JobRunner(queue, {}, FixedClock(now), "worker")
    await runner.run_once()
    assert queue.failures[0][1:] == ("PermanentProvider", None)
