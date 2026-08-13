"""Deletion orchestration that never accesses another module's tables."""

from dataclasses import dataclass
from datetime import timedelta

from qq_time_agent.contracts.clock import Clock
from qq_time_agent.modules.audit.contracts import AuditEvent, AuditPort
from qq_time_agent.modules.data_lifecycle.application.ports import TombstoneRepository
from qq_time_agent.modules.data_lifecycle.contracts import (
    ExpiredSourcePort,
    ExpiryPort,
    PurgePort,
    TombstoneRef,
)
from qq_time_agent.modules.data_lifecycle.domain.models import Tombstone, TombstoneStatus


@dataclass(frozen=True, slots=True)
class ExpiryTarget:
    port: ExpiryPort
    retention: timedelta


class DeletionCoordinator:
    def __init__(
        self,
        repository: TombstoneRepository,
        purge_ports: tuple[PurgePort, ...],
        clock: Clock,
        purge_within: timedelta,
        audit: AuditPort | None = None,
    ) -> None:
        if purge_within <= timedelta(0) or purge_within > timedelta(hours=24):
            raise ValueError("purge window must be between zero and 24 hours")
        self._repository = repository
        self._purge_ports = purge_ports
        self._clock = clock
        self._purge_within = purge_within
        self._audit = audit

    async def record_deletion(self, subject_ref: str) -> TombstoneRef:
        requested_at = self._clock.now()
        tombstone = Tombstone.request(subject_ref, requested_at, requested_at + self._purge_within)
        tombstone = await self._repository.add(tombstone)
        if tombstone.status is TombstoneStatus.COMPLETE:
            await self._replay_one(tombstone)
        else:
            await self._purge_one(tombstone)
        if self._audit is not None:
            await self._audit.append(
                AuditEvent(
                    "source-deleted",
                    "owner-or-retention",
                    subject_ref,
                    "SUCCEEDED",
                    requested_at,
                    {"tombstone_id": str(tombstone.tombstone_id)},
                )
            )
        return TombstoneRef(tombstone.tombstone_id, subject_ref, tombstone.purge_by)

    async def purge_due(self, limit: int = 100) -> int:
        if limit < 1:
            raise ValueError("limit must be positive")
        tombstones = await self._repository.find_due(self._clock.now(), limit)
        for tombstone in tombstones:
            await self._purge_one(tombstone)
        return len(tombstones)

    async def replay(self, limit: int = 1000) -> int:
        if limit < 1:
            raise ValueError("limit must be positive")
        tombstones = await self._repository.find_for_replay(limit)
        for tombstone in tombstones:
            await self._replay_one(tombstone)
        return len(tombstones)

    async def _purge_one(self, tombstone: Tombstone) -> None:
        for port in self._purge_ports:
            result = await port.purge_subject(tombstone.subject_ref, tombstone.tombstone_id)
            await self._repository.record_module_purge(
                tombstone.tombstone_id, result.module_name, result.deleted_count
            )
            tombstone.record_module_purge(result.module_name)
        required = {port.module_name for port in self._purge_ports}
        tombstone.complete(required)
        await self._repository.mark_complete(tombstone.tombstone_id)

    async def _replay_one(self, tombstone: Tombstone) -> None:
        for port in self._purge_ports:
            result = await port.purge_subject(tombstone.subject_ref, tombstone.tombstone_id)
            await self._repository.record_module_purge(
                tombstone.tombstone_id, result.module_name, result.deleted_count
            )


class RetentionCoordinator:
    def __init__(
        self,
        deletion: DeletionCoordinator,
        sources: ExpiredSourcePort,
        source_retention: timedelta,
        expiry_targets: tuple[ExpiryTarget, ...],
        clock: Clock,
    ) -> None:
        if source_retention <= timedelta(0):
            raise ValueError("source retention must be positive")
        self._deletion = deletion
        self._sources = sources
        self._source_retention = source_retention
        self._expiry_targets = expiry_targets
        self._clock = clock

    async def sweep(self, limit: int = 100) -> int:
        if limit < 1:
            raise ValueError("limit must be positive")
        now = self._clock.now()
        source_refs = await self._sources.find_expired(now - self._source_retention, limit)
        for source_ref in source_refs:
            await self._deletion.record_deletion(source_ref)
        count = len(source_refs)
        for target in self._expiry_targets:
            result = await target.port.purge_expired(now - target.retention, limit)
            count += result.deleted_count
        return count
