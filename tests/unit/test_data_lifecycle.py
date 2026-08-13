from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from qq_time_agent.modules.data_lifecycle.application.coordinator import (
    DeletionCoordinator,
    ExpiryTarget,
    RetentionCoordinator,
)
from qq_time_agent.modules.data_lifecycle.contracts.ports import PurgeResult
from qq_time_agent.modules.data_lifecycle.domain.models import Tombstone, TombstoneStatus


@dataclass
class FixedClock:
    value: datetime

    def now(self) -> datetime:
        return self.value


@dataclass
class MemoryRepository:
    items: list[Tombstone] = field(default_factory=list)
    results: set[tuple[UUID, str]] = field(default_factory=set)

    async def add(self, tombstone: Tombstone) -> Tombstone:
        existing = next(
            (item for item in self.items if item.subject_ref == tombstone.subject_ref), None
        )
        if existing is not None:
            return existing
        self.items.append(tombstone)
        return tombstone

    async def find_due(self, now: datetime, limit: int) -> list[Tombstone]:
        return [item for item in self.items if item.status is TombstoneStatus.PENDING][:limit]

    async def find_for_replay(self, limit: int) -> list[Tombstone]:
        return self.items[:limit]

    async def record_module_purge(
        self, tombstone_id: UUID, module_name: str, deleted_count: int
    ) -> None:
        self.results.add((tombstone_id, module_name))

    async def mark_complete(self, tombstone_id: UUID) -> None:
        next(
            item for item in self.items if item.tombstone_id == tombstone_id
        ).status = TombstoneStatus.COMPLETE


@dataclass
class RecordingPurgePort:
    module_name: str
    calls: list[tuple[str, UUID]] = field(default_factory=list)

    async def purge_subject(self, subject_ref: str, tombstone_id: UUID) -> PurgeResult:
        self.calls.append((subject_ref, tombstone_id))
        return PurgeResult(self.module_name, 1)


@dataclass
class ExpiredSources:
    values: tuple[str, ...]

    async def find_expired(self, cutoff: datetime, limit: int) -> tuple[str, ...]:
        return self.values[:limit]


@dataclass
class Expiry:
    module_name: str
    calls: list[datetime] = field(default_factory=list)

    async def purge_expired(self, cutoff: datetime, limit: int) -> PurgeResult:
        self.calls.append(cutoff)
        return PurgeResult(self.module_name, 2)


@pytest.mark.asyncio
async def test_deletion_is_recorded_then_purged_through_module_ports() -> None:
    start = datetime(2026, 8, 13, tzinfo=UTC)
    clock = FixedClock(start)
    repository = MemoryRepository()
    knowledge = RecordingPurgePort("knowledge")
    inbox = RecordingPurgePort("inbox")
    coordinator = DeletionCoordinator(repository, (knowledge, inbox), clock, timedelta(hours=24))

    reference = await coordinator.record_deletion("mail:42")
    assert repository.items[0].status is TombstoneStatus.COMPLETE
    assert knowledge.calls == [("mail:42", reference.tombstone_id)]
    assert inbox.calls == [("mail:42", reference.tombstone_id)]
    clock.value = start + timedelta(hours=24)
    completed = await coordinator.purge_due()

    assert completed == 0

    assert await coordinator.replay() == 1
    assert knowledge.calls[-1] == ("mail:42", reference.tombstone_id)
    assert inbox.calls[-1] == ("mail:42", reference.tombstone_id)

    duplicate = await coordinator.record_deletion("mail:42")
    assert duplicate.tombstone_id == reference.tombstone_id
    assert len(repository.items) == 1


def test_tombstone_rejects_naive_time() -> None:
    naive = datetime(2026, 8, 13)
    with pytest.raises(ValueError, match="timezone-aware"):
        Tombstone.request("mail:42", naive, naive + timedelta(hours=1))


def test_tombstone_rejects_invalid_subject_and_completion_order() -> None:
    now = datetime(2026, 8, 13, tzinfo=UTC)
    with pytest.raises(ValueError, match="subject_ref"):
        Tombstone.request(" ", now, now)
    tombstone = Tombstone.request("mail:42", now, now)
    with pytest.raises(ValueError, match="all module purges"):
        tombstone.complete({"knowledge"})
    with pytest.raises(ValueError, match="module_name"):
        tombstone.record_module_purge(" ")
    with pytest.raises(ValueError, match="purge_by"):
        Tombstone.request("mail:42", now, now - timedelta(seconds=1))


def test_completed_tombstone_ignores_replayed_module_result() -> None:
    now = datetime(2026, 8, 13, tzinfo=UTC)
    tombstone = Tombstone.request("mail:42", now, now)
    tombstone.complete(set())
    tombstone.record_module_purge("knowledge")
    assert tombstone.completed_modules == set()


@pytest.mark.asyncio
async def test_coordinator_validates_purge_window_and_batch_limit() -> None:
    now = datetime(2026, 8, 13, tzinfo=UTC)
    repository = MemoryRepository()
    with pytest.raises(ValueError, match="purge window"):
        DeletionCoordinator(repository, (), FixedClock(now), timedelta(hours=25))
    coordinator = DeletionCoordinator(repository, (), FixedClock(now), timedelta(hours=1))
    with pytest.raises(ValueError, match="limit"):
        await coordinator.purge_due(0)


@pytest.mark.asyncio
async def test_retention_uses_configured_cutoffs_and_source_tombstones() -> None:
    now = datetime(2026, 8, 20, tzinfo=UTC)
    repository = MemoryRepository()
    deletion = DeletionCoordinator(repository, (), FixedClock(now), timedelta(hours=24))
    expiry = Expiry("metadata")
    retention = RetentionCoordinator(
        deletion,
        ExpiredSources(("mail:old",)),
        timedelta(days=365),
        (ExpiryTarget(expiry, timedelta(days=180)),),
        FixedClock(now),
    )
    assert await retention.sweep() == 3
    assert repository.items[0].subject_ref == "mail:old"
    assert expiry.calls == [now - timedelta(days=180)]
    with pytest.raises(ValueError, match="limit"):
        await retention.sweep(0)
    with pytest.raises(ValueError, match="source retention"):
        RetentionCoordinator(deletion, ExpiredSources(()), timedelta(0), (), FixedClock(now))
