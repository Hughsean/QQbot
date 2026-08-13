"""PostgreSQL repository for replayable tombstones."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from qq_time_agent.contracts.clock import Clock
from qq_time_agent.modules.data_lifecycle.domain.models import Tombstone, TombstoneStatus
from qq_time_agent.modules.data_lifecycle.infrastructure.tables import (
    PurgeResultRow,
    TombstoneRow,
)


class SqlTombstoneRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], clock: Clock) -> None:
        self._sessions = sessions
        self._clock = clock

    async def add(self, tombstone: Tombstone) -> Tombstone:
        values = {
            "tombstone_id": tombstone.tombstone_id,
            "subject_ref": tombstone.subject_ref,
            "requested_at": tombstone.requested_at,
            "purge_by": tombstone.purge_by,
            "status": tombstone.status.value,
        }
        async with self._sessions.begin() as session:
            await session.execute(
                insert(TombstoneRow)
                .values(**values)
                .on_conflict_do_nothing(constraint="uq_lifecycle_tombstone_subject")
            )
            row = await session.scalar(
                select(TombstoneRow).where(TombstoneRow.subject_ref == tombstone.subject_ref)
            )
            if row is None:
                raise RuntimeError("idempotent tombstone insert lost stored deletion")
            stored = _to_domain(row)
            await self._load_results(session, [stored])
            return stored

    async def find_due(self, now: datetime, limit: int) -> list[Tombstone]:
        del now
        async with self._sessions() as session:
            rows = list(
                await session.scalars(
                    select(TombstoneRow)
                    .where(
                        TombstoneRow.status == TombstoneStatus.PENDING.value,
                    )
                    .order_by(TombstoneRow.purge_by, TombstoneRow.tombstone_id)
                    .limit(limit)
                )
            )
            tombstones = [_to_domain(row) for row in rows]
            await self._load_results(session, tombstones)
            return tombstones

    async def find_for_replay(self, limit: int) -> list[Tombstone]:
        async with self._sessions() as session:
            rows = list(
                await session.scalars(
                    select(TombstoneRow)
                    .order_by(TombstoneRow.requested_at, TombstoneRow.tombstone_id)
                    .limit(limit)
                )
            )
            tombstones = [_to_domain(row) for row in rows]
            await self._load_results(session, tombstones)
            return tombstones

    async def record_module_purge(
        self, tombstone_id: UUID, module_name: str, deleted_count: int
    ) -> None:
        values = {
            "result_id": uuid4(),
            "tombstone_id": tombstone_id,
            "module_name": module_name,
            "deleted_count": deleted_count,
            "completed_at": self._clock.now(),
        }
        async with self._sessions.begin() as session:
            statement = (
                insert(PurgeResultRow)
                .values(**values)
                .on_conflict_do_update(
                    constraint="uq_purge_result_module",
                    set_={"deleted_count": deleted_count, "completed_at": values["completed_at"]},
                )
            )
            await session.execute(statement)

    async def mark_complete(self, tombstone_id: UUID) -> None:
        now = self._clock.now()
        async with self._sessions.begin() as session:
            await session.execute(
                update(TombstoneRow)
                .where(TombstoneRow.tombstone_id == tombstone_id)
                .values(status=TombstoneStatus.COMPLETE.value, completed_at=now)
            )

    @staticmethod
    async def _load_results(session: AsyncSession, tombstones: list[Tombstone]) -> None:
        if not tombstones:
            return
        by_id = {item.tombstone_id: item for item in tombstones}
        results = await session.execute(
            select(PurgeResultRow.tombstone_id, PurgeResultRow.module_name).where(
                PurgeResultRow.tombstone_id.in_(by_id)
            )
        )
        for tombstone_id, module_name in results:
            by_id[tombstone_id].record_module_purge(module_name)


def _to_domain(row: TombstoneRow) -> Tombstone:
    return Tombstone(
        tombstone_id=row.tombstone_id,
        subject_ref=row.subject_ref,
        requested_at=row.requested_at,
        purge_by=row.purge_by,
        status=TombstoneStatus(row.status),
    )
