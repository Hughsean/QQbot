"""PostgreSQL job queue with leases and idempotent enqueue."""

from datetime import datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql.elements import ColumnElement

from qq_time_agent.adapters.outbound.persistence.operations_tables import JobRow
from qq_time_agent.contracts.jobs import JobLease, JobRequest, JobStatusView


class SqlJobQueue:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def enqueue(self, request: JobRequest) -> UUID:
        _validate_request(request)
        job_id = uuid4()
        values = {
            "job_id": job_id,
            "kind": request.kind,
            "payload": request.payload,
            "status": "PENDING",
            "idempotency_key": request.idempotency_key,
            "available_at": request.available_at,
            "attempt_count": 0,
            "max_attempts": request.max_attempts,
            "created_at": request.available_at,
            "updated_at": request.available_at,
        }
        async with self._sessions.begin() as session:
            statement = (
                insert(JobRow)
                .values(**values)
                .on_conflict_do_nothing(index_elements=[JobRow.idempotency_key])
            )
            result = await session.execute(statement.returning(JobRow.job_id))
            inserted = result.scalar_one_or_none()
            if inserted is not None:
                return inserted
            existing = await session.scalar(
                select(JobRow.job_id).where(JobRow.idempotency_key == request.idempotency_key)
            )
            if existing is None:
                raise RuntimeError("idempotent enqueue lost existing job")
            return existing

    async def lease_due(
        self, now: datetime, worker_id: str, limit: int, lease_duration: timedelta
    ) -> list[JobLease]:
        if limit < 1 or lease_duration <= timedelta(0):
            raise ValueError("positive lease limit and duration required")
        async with self._sessions.begin() as session:
            rows = list(
                await session.scalars(
                    select(JobRow)
                    .where(_leaseable(now))
                    .order_by(JobRow.available_at, JobRow.job_id)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            )
            lease_until = now + lease_duration
            for row in rows:
                row.status = "LEASED"
                row.lease_owner = worker_id
                row.lease_until = lease_until
                row.attempt_count += 1
                row.updated_at = now
            return [_to_lease(row, worker_id) for row in rows]

    async def complete(self, lease: JobLease, now: datetime) -> None:
        await self._finish(lease, now, "COMPLETE", None, None)

    async def fail(
        self,
        lease: JobLease,
        now: datetime,
        failure_class: str,
        retry_at: datetime | None,
    ) -> None:
        exhausted = lease.attempt_count >= lease.max_attempts or retry_at is None
        status = "DEAD_LETTER" if exhausted else "RETRY_WAIT"
        await self._finish(lease, now, status, failure_class, retry_at)

    async def status(self, job_id: UUID) -> JobStatusView | None:
        async with self._sessions() as session:
            row = await session.get(JobRow, job_id)
            if row is None:
                return None
            return JobStatusView(
                row.job_id,
                row.kind,
                row.status,
                row.attempt_count,
                row.max_attempts,
                row.last_error_class,
                row.updated_at,
            )

    async def cancel_pending_for_connection(
        self, connection_id: UUID, cancelled_at: datetime
    ) -> int:
        async with self._sessions.begin() as session:
            result = await session.execute(
                update(JobRow)
                .where(
                    JobRow.kind.in_(("microsoft-mail-sync", "qq-mail-sync")),
                    JobRow.payload["connection_id"].as_string() == str(connection_id),
                    JobRow.status.in_(("PENDING", "RETRY_WAIT")),
                )
                .values(status="CANCELLED", updated_at=cancelled_at)
            )
            return int(cast("CursorResult[tuple[()]]", result).rowcount or 0)

    async def _finish(
        self,
        lease: JobLease,
        now: datetime,
        status: str,
        failure_class: str | None,
        available_at: datetime | None,
    ) -> None:
        values: dict[str, object] = {
            "status": status,
            "lease_owner": None,
            "lease_until": None,
            "updated_at": now,
            "last_error_class": failure_class,
        }
        if available_at is not None:
            values["available_at"] = available_at
        async with self._sessions.begin() as session:
            result = await session.execute(
                update(JobRow)
                .where(
                    JobRow.job_id == lease.job_id,
                    JobRow.status == "LEASED",
                    JobRow.lease_owner == lease.lease_owner,
                )
                .values(**values)
            )
            cursor = cast("CursorResult[tuple[()]]", result)
            if cursor.rowcount != 1:
                raise RuntimeError("job lease is stale or no longer owned")


def _leaseable(now: datetime) -> ColumnElement[bool]:
    return and_(
        JobRow.available_at <= now,
        or_(
            JobRow.status.in_(("PENDING", "RETRY_WAIT")),
            and_(JobRow.status == "LEASED", JobRow.lease_until < now),
        ),
    )


def _to_lease(row: JobRow, worker_id: str) -> JobLease:
    return JobLease(
        row.job_id,
        row.kind,
        row.payload,
        worker_id,
        row.attempt_count,
        row.max_attempts,
    )


def _validate_request(request: JobRequest) -> None:
    if not request.kind.strip() or not request.idempotency_key.strip():
        raise ValueError("job kind and idempotency key are required")
    if request.available_at.tzinfo is None or request.available_at.utcoffset() is None:
        raise ValueError("job available_at must be timezone-aware")
    if request.max_attempts < 1:
        raise ValueError("max_attempts must be positive")
