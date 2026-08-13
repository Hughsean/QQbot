"""Versioned operational job contract shared by application use cases."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class JobRequest:
    kind: str
    payload: dict[str, object]
    idempotency_key: str
    available_at: datetime
    max_attempts: int = 5


@dataclass(frozen=True, slots=True)
class JobLease:
    job_id: UUID
    kind: str
    payload: dict[str, object]
    lease_owner: str
    attempt_count: int
    max_attempts: int


@dataclass(frozen=True, slots=True)
class JobStatusView:
    job_id: UUID
    kind: str
    status: str
    attempt_count: int
    max_attempts: int
    last_error_class: str | None
    updated_at: datetime


class JobQueue(Protocol):
    async def enqueue(self, request: JobRequest) -> UUID: ...

    async def lease_due(
        self, now: datetime, worker_id: str, limit: int, lease_duration: timedelta
    ) -> list[JobLease]: ...

    async def complete(self, lease: JobLease, now: datetime) -> None: ...

    async def fail(
        self,
        lease: JobLease,
        now: datetime,
        failure_class: str,
        retry_at: datetime | None,
    ) -> None: ...

    async def status(self, job_id: UUID) -> JobStatusView | None: ...
