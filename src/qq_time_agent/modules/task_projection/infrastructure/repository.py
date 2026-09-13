"""PostgreSQL Task Projection target repository."""

from typing import cast
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from qq_time_agent.modules.task_projection.domain.models import (
    TaskProjectionCursor,
    TaskProjectionMapping,
    TaskProjectionProvider,
    TaskProjectionStatus,
    TaskProjectionTarget,
    TaskProjectionTargetStatus,
)
from qq_time_agent.modules.task_projection.infrastructure.tables import (
    TaskProjectionCursorRow,
    TaskProjectionMappingRow,
    TaskProjectionTargetRow,
)


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

    async def list_ready(self, user_id: str) -> tuple[TaskProjectionTarget, ...]:
        async with self._sessions() as session:
            rows = await session.scalars(
                select(TaskProjectionTargetRow)
                .where(
                    TaskProjectionTargetRow.user_id == user_id,
                    TaskProjectionTargetRow.status == TaskProjectionTargetStatus.READY.value,
                )
                .order_by(TaskProjectionTargetRow.connection_id)
            )
            return tuple(_to_target(row) for row in rows)


class SqlTaskProjectionMappingRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def get_for_agenda(
        self, connection_id: UUID, agenda_entry_id: UUID
    ) -> TaskProjectionMapping | None:
        async with self._sessions() as session:
            row = await session.scalar(
                select(TaskProjectionMappingRow).where(
                    TaskProjectionMappingRow.connection_id == connection_id,
                    TaskProjectionMappingRow.agenda_entry_id == agenda_entry_id,
                    TaskProjectionMappingRow.provider
                    == TaskProjectionProvider.MICROSOFT_TODO.value,
                )
            )
            return None if row is None else _to_mapping(row)

    async def list_for_agenda(self, agenda_entry_id: UUID) -> tuple[TaskProjectionMapping, ...]:
        async with self._sessions() as session:
            rows = await session.scalars(
                select(TaskProjectionMappingRow)
                .where(TaskProjectionMappingRow.agenda_entry_id == agenda_entry_id)
                .order_by(TaskProjectionMappingRow.connection_id)
            )
            return tuple(_to_mapping(row) for row in rows)

    async def get_for_external_task(
        self, connection_id: UUID, provider_list_ref: str, provider_task_ref: str
    ) -> TaskProjectionMapping | None:
        async with self._sessions() as session:
            row = await session.scalar(
                select(TaskProjectionMappingRow).where(
                    TaskProjectionMappingRow.connection_id == connection_id,
                    TaskProjectionMappingRow.provider_list_ref == provider_list_ref,
                    TaskProjectionMappingRow.provider_task_ref == provider_task_ref,
                    TaskProjectionMappingRow.provider
                    == TaskProjectionProvider.MICROSOFT_TODO.value,
                )
            )
            return None if row is None else _to_mapping(row)

    async def add_or_get(self, mapping: TaskProjectionMapping) -> TaskProjectionMapping:
        async with self._sessions.begin() as session:
            await session.execute(
                insert(TaskProjectionMappingRow)
                .values(**_mapping_values(mapping))
                .on_conflict_do_nothing(constraint="uq_task_projection_mapping_agenda")
            )
            row = await session.scalar(
                select(TaskProjectionMappingRow).where(
                    TaskProjectionMappingRow.connection_id == mapping.connection_id,
                    TaskProjectionMappingRow.agenda_entry_id == mapping.agenda_entry_id,
                    TaskProjectionMappingRow.provider == mapping.provider.value,
                )
            )
            if row is None:
                raise RuntimeError("idempotent task projection mapping insert lost row")
            return _to_mapping(row)

    async def save(self, mapping: TaskProjectionMapping, expected_version: int) -> None:
        values = _mapping_values(mapping)
        values.pop("mapping_id")
        async with self._sessions.begin() as session:
            result = await session.execute(
                update(TaskProjectionMappingRow)
                .where(
                    TaskProjectionMappingRow.mapping_id == mapping.mapping_id,
                    TaskProjectionMappingRow.version == expected_version,
                )
                .values(**values)
            )
            if cast("CursorResult[tuple[()]]", result).rowcount != 1:
                raise RuntimeError("stale task projection mapping update")


class SqlTaskProjectionCursorRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def get(self, connection_id: UUID, provider_list_ref: str) -> TaskProjectionCursor | None:
        async with self._sessions() as session:
            row = await session.scalar(
                select(TaskProjectionCursorRow).where(
                    TaskProjectionCursorRow.connection_id == connection_id,
                    TaskProjectionCursorRow.provider_list_ref == provider_list_ref,
                    TaskProjectionCursorRow.provider == TaskProjectionProvider.MICROSOFT_TODO.value,
                )
            )
            return None if row is None else _to_cursor(row)

    async def save(self, cursor: TaskProjectionCursor, expected_version: int | None) -> None:
        async with self._sessions.begin() as session:
            if expected_version is None:
                await session.execute(
                    insert(TaskProjectionCursorRow)
                    .values(**_cursor_values(cursor))
                    .on_conflict_do_nothing(constraint="uq_task_projection_cursor_target")
                )
                return
            values = _cursor_values(cursor)
            values.pop("cursor_id")
            result = await session.execute(
                update(TaskProjectionCursorRow)
                .where(
                    TaskProjectionCursorRow.cursor_id == cursor.cursor_id,
                    TaskProjectionCursorRow.version == expected_version,
                )
                .values(**values)
            )
            if cast("CursorResult[tuple[()]]", result).rowcount != 1:
                raise RuntimeError("stale task projection cursor update")

    async def delete(self, connection_id: UUID, provider_list_ref: str) -> None:
        async with self._sessions.begin() as session:
            await session.execute(
                delete(TaskProjectionCursorRow).where(
                    TaskProjectionCursorRow.connection_id == connection_id,
                    TaskProjectionCursorRow.provider_list_ref == provider_list_ref,
                    TaskProjectionCursorRow.provider == TaskProjectionProvider.MICROSOFT_TODO.value,
                )
            )


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


def _mapping_values(value: TaskProjectionMapping) -> dict[str, object]:
    return {
        "mapping_id": value.mapping_id,
        "user_id": value.user_id,
        "agenda_entry_id": value.agenda_entry_id,
        "agenda_entry_version": value.agenda_entry_version,
        "connection_id": value.connection_id,
        "provider": value.provider.value,
        "provider_list_ref": value.provider_list_ref,
        "provider_task_ref": value.provider_task_ref,
        "status": value.status.value,
        "provider_revision": value.provider_revision,
        "last_projected_at": value.last_projected_at,
        "last_checked_at": value.last_checked_at,
        "last_observed_completion": value.last_observed_completion,
        "version": value.version,
    }


def _to_mapping(row: TaskProjectionMappingRow) -> TaskProjectionMapping:
    return TaskProjectionMapping(
        row.mapping_id,
        row.user_id,
        row.agenda_entry_id,
        row.agenda_entry_version,
        row.connection_id,
        TaskProjectionProvider(row.provider),
        row.provider_list_ref,
        row.provider_task_ref,
        TaskProjectionStatus(row.status),
        row.provider_revision,
        row.last_projected_at,
        row.last_checked_at,
        row.last_observed_completion,
        row.version,
    )


def _cursor_values(value: TaskProjectionCursor) -> dict[str, object]:
    return {
        "cursor_id": value.cursor_id,
        "connection_id": value.connection_id,
        "provider": value.provider.value,
        "provider_list_ref": value.provider_list_ref,
        "opaque_cursor": value.opaque_cursor,
        "updated_at": value.updated_at,
        "version": value.version,
    }


def _to_cursor(row: TaskProjectionCursorRow) -> TaskProjectionCursor:
    return TaskProjectionCursor(
        row.cursor_id,
        row.connection_id,
        TaskProjectionProvider(row.provider),
        row.provider_list_ref,
        row.opaque_cursor,
        row.updated_at,
        row.version,
    )
