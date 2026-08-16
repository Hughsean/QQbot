"""Idempotent periodic enqueue for one provider connection."""

from typing import Protocol

from qq_time_agent.contracts.clock import Clock
from qq_time_agent.contracts.jobs import JobQueue, JobRequest
from qq_time_agent.modules.connections.contracts import ConnectionStatusView


class ConnectionStatusLookup(Protocol):
    async def statuses(self, user_id: str) -> tuple[ConnectionStatusView, ...]: ...


class PeriodicMailSyncScheduler:
    def __init__(
        self,
        connections: ConnectionStatusLookup,
        queue: JobQueue,
        clock: Clock,
        interval_seconds: int,
        job_kind: str = "microsoft-mail-sync",
    ) -> None:
        if interval_seconds < 60:
            raise ValueError("mail sync interval must be at least 60 seconds")
        self._connections = connections
        self._queue = queue
        self._clock = clock
        self._interval_seconds = interval_seconds
        if job_kind not in {"microsoft-mail-sync", "qq-mail-sync"}:
            raise ValueError("unsupported mail sync job kind")
        self._job_kind = job_kind

    async def enqueue_due(self) -> None:
        connections = await self._connections.statuses("owner")
        now = self._clock.now()
        bucket = int(now.timestamp()) // self._interval_seconds
        for connection in connections:
            if connection.status not in {"ACTIVE", "DEGRADED"} or not connection.sync_enabled:
                continue
            await self._queue.enqueue(
                JobRequest(
                    self._job_kind,
                    {"connection_id": str(connection.connection_id)},
                    f"{self._job_kind}:{connection.connection_id}:{bucket}",
                    now,
                )
            )
