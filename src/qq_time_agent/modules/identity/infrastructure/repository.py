"""PostgreSQL single-owner preferences repository."""

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from qq_time_agent.modules.identity.contracts import UserPreferencesView
from qq_time_agent.modules.identity.infrastructure.tables import UserPreferencesRow


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
    )
