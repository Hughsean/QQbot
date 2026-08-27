"""PostgreSQL repositories for single-owner Identity state."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from qq_time_agent.modules.identity.contracts import OwnerGroupAlias, UserPreferencesView
from qq_time_agent.modules.identity.infrastructure.tables import (
    OwnerGroupAliasRow,
    UserPreferencesRow,
)


class SqlUserPreferencesRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def get(self, user_id: str) -> UserPreferencesView | None:
        async with self._sessions() as session:
            row = await session.get(UserPreferencesRow, user_id)
            return None if row is None else _view(row)

    async def initialize(self, value: UserPreferencesView) -> UserPreferencesView:
        values = {
            "user_id": value.user_id,
            "timezone": value.timezone,
            "work_start": value.work_start,
            "work_end": value.work_end,
            "lunch_start": value.lunch_start,
            "lunch_end": value.lunch_end,
            "working_weekdays": list(value.working_weekdays),
            "default_event_minutes": value.default_event_minutes,
            "default_task_minutes": value.default_task_minutes,
            "digest_enabled": value.digest_enabled,
            "digest_local_time": value.digest_local_time,
            "conflict_notifications_enabled": value.conflict_notifications_enabled,
            "reauth_notifications_enabled": value.reauth_notifications_enabled,
            "quiet_hours_enabled": value.quiet_hours_enabled,
            "quiet_start": value.quiet_start,
            "quiet_end": value.quiet_end,
        }
        async with self._sessions.begin() as session:
            await session.execute(
                insert(UserPreferencesRow)
                .values(**values)
                .on_conflict_do_nothing(index_elements=[UserPreferencesRow.user_id])
            )
            row = await session.get(UserPreferencesRow, value.user_id)
            if row is None:
                raise RuntimeError("Identity initialization lost owner preferences")
            return _view(row)


def _view(row: UserPreferencesRow) -> UserPreferencesView:
    return UserPreferencesView(
        row.user_id,
        row.timezone,
        row.work_start,
        row.work_end,
        row.lunch_start,
        row.lunch_end,
        tuple(row.working_weekdays),
        row.default_event_minutes,
        row.default_task_minutes,
        row.digest_enabled,
        row.digest_local_time,
        row.conflict_notifications_enabled,
        row.reauth_notifications_enabled,
        row.quiet_hours_enabled,
        row.quiet_start,
        row.quiet_end,
    )


class SqlOwnerGroupAliasRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def list(self, user_id: str) -> tuple[OwnerGroupAlias, ...]:
        async with self._sessions() as session:
            rows = await session.scalars(
                select(OwnerGroupAliasRow)
                .where(OwnerGroupAliasRow.user_id == user_id)
                .order_by(OwnerGroupAliasRow.alias)
            )
            return tuple(OwnerGroupAlias(row.alias) for row in rows)

    async def add_or_get(
        self, user_id: str, alias: OwnerGroupAlias, normalized_alias: str, now: datetime
    ) -> OwnerGroupAlias:
        async with self._sessions.begin() as session:
            await session.execute(
                insert(OwnerGroupAliasRow)
                .values(
                    user_id=user_id,
                    normalized_alias=normalized_alias,
                    alias=alias.alias,
                    created_at=now,
                )
                .on_conflict_do_nothing()
            )
            row = await session.get(OwnerGroupAliasRow, (user_id, normalized_alias))
            if row is None:
                raise RuntimeError("Identity alias idempotent insert lost stored row")
            return OwnerGroupAlias(row.alias)
