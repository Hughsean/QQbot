"""Bounded aggregate operational metrics read model without content labels."""

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql.elements import ColumnElement

from qq_time_agent.adapters.outbound.persistence.operations_tables import JobRow
from qq_time_agent.modules.actions.infrastructure.tables import ActionRow
from qq_time_agent.modules.data_lifecycle.infrastructure.tables import TombstoneRow
from qq_time_agent.modules.reminders.infrastructure.tables import ReminderRow


class SqlMetricsSnapshot:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def snapshot(self) -> dict[str, float]:
        async with self._sessions() as session:
            pending_jobs = await _count(
                session, JobRow, JobRow.status.in_(("PENDING", "RETRY_WAIT"))
            )
            dead_jobs = await _count(session, JobRow, JobRow.status == "DEAD_LETTER")
            due_reminders = await _count(
                session, ReminderRow, ReminderRow.status.in_(("PENDING", "RETRY_WAIT"))
            )
            dead_reminders = await _count(session, ReminderRow, ReminderRow.status == "DEAD_LETTER")
            pending_deletions = await _count(
                session, TombstoneRow, TombstoneRow.status == "PENDING"
            )
            actions = tuple(
                await session.scalars(select(ActionRow).where(ActionRow.status == "SUCCEEDED"))
            )
        created = tuple(value for value in actions if value.action_type == "CREATE_AGENDA")
        cancelled = tuple(value for value in actions if value.action_type == "CANCEL_AGENDA")
        quick_undo = _quick_undo_count(created, cancelled)
        return {
            "jobs_pending": pending_jobs,
            "jobs_dead_letter": dead_jobs,
            "reminders_pending": due_reminders,
            "reminders_dead_letter": dead_reminders,
            "deletions_pending": pending_deletions,
            "agenda_created_total": float(len(created)),
            "agenda_cancelled_total": float(len(cancelled)),
            "agenda_undo_rate": _ratio(len(cancelled), len(created)),
            "agenda_quick_undo_rate": _ratio(quick_undo, len(created)),
        }


async def _count(
    session: AsyncSession, table: type[object], condition: ColumnElement[bool]
) -> float:
    value = await session.scalar(select(func.count()).select_from(table).where(condition))
    return float(value or 0)


def _quick_undo_count(created: tuple[ActionRow, ...], cancelled: tuple[ActionRow, ...]) -> int:
    created_by_entry = {
        value.agenda_entry_id: value.requested_at
        for value in created
        if value.agenda_entry_id is not None
    }
    return sum(
        1
        for value in cancelled
        if value.agenda_entry_id in created_by_entry
        and value.requested_at - created_by_entry[value.agenda_entry_id] <= timedelta(minutes=10)
    )


def _ratio(numerator: int, denominator: int) -> float:
    return 0.0 if denominator == 0 else numerator / denominator
