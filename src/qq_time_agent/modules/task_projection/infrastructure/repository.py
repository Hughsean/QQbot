"""PostgreSQL Task Projection target repository."""

from typing import cast
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from qq_time_agent.modules.task_projection.domain.models import (
    TaskProjectionProvider,
    TaskProjectionTarget,
    TaskProjectionTargetStatus,
)
from qq_time_agent.modules.task_projection.infrastructure.tables import TaskProjectionTargetRow


class SqlTaskProjectionTargetRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def get_for_connection(self, connection_id: UUID) -> TaskProjectionTarget | None:
        async with self._sessions() as session:
            row = await session.scalar(
                select(TaskProjectionTargetRow).where(
                    TaskProjectionTargetRow.connection_id == connection_id,
                    TaskProjectionTargetRow.provider == TaskProjectionProvider.MICROSOFT_TODO.value,
                )
            )
            return None if row is None else _to_target(row)

    async def add_or_get(self, target: TaskProjectionTarget) -> TaskProjectionTarget:
        async with self._sessions.begin() as session:
            await session.execute(
                insert(TaskProjectionTargetRow)
                .values(**_values(target))
                .on_conflict_do_nothing(constraint="uq_task_projection_target_connection")
            )
            row = await session.scalar(
                select(TaskProjectionTargetRow).where(
                    TaskProjectionTargetRow.connection_id == target.connection_id,
                    TaskProjectionTargetRow.provider == target.provider.value,
                )
            )
            if row is None:
                raise RuntimeError("idempotent task projection target insert lost row")
            return _to_target(row)

    async def save(self, target: TaskProjectionTarget, expected_version: int) -> None:
        async with self._sessions.begin() as session:
            result = await session.execute(
                update(TaskProjectionTargetRow)
                .where(
                    TaskProjectionTargetRow.target_id == target.target_id,
                    TaskProjectionTargetRow.version == expected_version,
                )
                .values(**_values(target))
            )
            if cast("CursorResult[tuple[()]]", result).rowcount != 1:
                raise RuntimeError("stale task projection target update")


def _values(value: TaskProjectionTarget) -> dict[str, object]:
    return {
        "target_id": value.target_id,
        "user_id": value.user_id,
        "connection_id": value.connection_id,
        "provider": value.provider.value,
        "provider_list_ref": value.provider_list_ref,
        "display_name": value.display_name,
        "status": value.status.value,
        "resolved_at": value.resolved_at,
        "updated_at": value.updated_at,
        "version": value.version,
    }


def _to_target(row: TaskProjectionTargetRow) -> TaskProjectionTarget:
    return TaskProjectionTarget(
        row.target_id,
        row.user_id,
        row.connection_id,
        TaskProjectionProvider(row.provider),
        row.provider_list_ref,
        row.display_name,
        TaskProjectionTargetStatus(row.status),
        row.resolved_at,
        row.updated_at,
        row.version,
    )
