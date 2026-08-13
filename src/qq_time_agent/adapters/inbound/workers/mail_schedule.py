"""Idempotent periodic enqueue for the single owner's Microsoft connection."""

from typing import Protocol

from qq_time_agent.contracts.clock import Clock
from qq_time_agent.contracts.jobs import JobQueue, JobRequest
from qq_time_agent.modules.connections.contracts import ConnectionStatusView

MAIL_SYNC_JOB = "microsoft-mail-sync"


class ConnectionStatusLookup(Protocol):
    async def status(self, user_id: str) -> ConnectionStatusView | None: ...


class PeriodicMailSyncScheduler:
    def __init__(
        self,
        connections: ConnectionStatusLookup,
        queue: JobQueue,
        clock: Clock,
        interval_seconds: int,
    ) -> None:
        if interval_seconds < 60:
            raise ValueError("mail sync interval must be at least 60 seconds")
        self._connections = connections
        self._queue = queue
        self._clock = clock
        self._interval_seconds = interval_seconds

    async def enqueue_due(self) -> None:
        connection = await self._connections.status("owner")
        if connection is None or connection.status not in {"ACTIVE", "DEGRADED"}:
            return
        now = self._clock.now()
        bucket = int(now.timestamp()) // self._interval_seconds
        await self._queue.enqueue(
            JobRequest(
                MAIL_SYNC_JOB,
                {"connection_id": str(connection.connection_id)},
                f"mail-sync:{connection.connection_id}:{bucket}",
                now,
            )
        )
