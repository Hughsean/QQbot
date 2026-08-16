"""Periodic retention, deletion retry, and tombstone replay handler."""

from datetime import datetime
from typing import Protocol

from qq_time_agent.contracts.clock import Clock
from qq_time_agent.contracts.jobs import JobLease
from qq_time_agent.modules.data_lifecycle.application.coordinator import (
    DeletionCoordinator,
    RetentionCoordinator,
)


class SourceAssetCleanupPort(Protocol):
    async def cleanup_expired(self) -> int: ...


class SourceAssetRecoveryPort(Protocol):
    async def recover_pending(self, now: datetime, limit: int = 100) -> int: ...


class DataLifecycleJobHandler:
    def __init__(
        self,
        deletion: DeletionCoordinator,
        retention: RetentionCoordinator,
        asset_cleanup: SourceAssetCleanupPort,
        asset_recovery: SourceAssetRecoveryPort,
        clock: Clock,
    ) -> None:
        self._deletion = deletion
        self._retention = retention
        self._asset_cleanup = asset_cleanup
        self._asset_recovery = asset_recovery
        self._clock = clock

    async def __call__(self, job: JobLease) -> None:
        del job
        await self._asset_recovery.recover_pending(self._clock.now())
        await self._asset_cleanup.cleanup_expired()
        await self._deletion.purge_due()
        await self._retention.sweep()


class TombstoneReplayJobHandler:
    def __init__(self, deletion: DeletionCoordinator) -> None:
        self._deletion = deletion

    async def __call__(self, job: JobLease) -> None:
        del job
        await self._deletion.replay()
