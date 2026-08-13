"""Periodic retention, deletion retry, and tombstone replay handler."""

from qq_time_agent.contracts.jobs import JobLease
from qq_time_agent.modules.data_lifecycle.application.coordinator import (
    DeletionCoordinator,
    RetentionCoordinator,
)


class DataLifecycleJobHandler:
    def __init__(self, deletion: DeletionCoordinator, retention: RetentionCoordinator) -> None:
        self._deletion = deletion
        self._retention = retention

    async def __call__(self, job: JobLease) -> None:
        del job
        await self._deletion.purge_due()
        await self._retention.sweep()


class TombstoneReplayJobHandler:
    def __init__(self, deletion: DeletionCoordinator) -> None:
        self._deletion = deletion

    async def __call__(self, job: JobLease) -> None:
        del job
        await self._deletion.replay()
