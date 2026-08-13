"""PostgreSQL Reminder repository with durable due-row locking."""

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from qq_time_agent.modules.reminders.domain.models import Reminder, ReminderStatus
from qq_time_agent.modules.reminders.infrastructure.tables import ReminderRow


class SqlReminderRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def add(self, value: Reminder) -> Reminder:
        async with self._sessions.begin() as session:
            await session.execute(
                insert(ReminderRow)
                .values(**_values(value))
                .on_conflict_do_nothing(constraint="uq_reminders_idempotency")
            )
            row = await session.scalar(
                select(ReminderRow).where(ReminderRow.idempotency_key == value.idempotency_key)
            )
            if row is None:
                raise RuntimeError("idempotent Reminder insert lost stored row")
            return _to_reminder(row)

    async def get(self, reminder_id: UUID) -> Reminder | None:
        async with self._sessions() as session:
            row = await session.get(ReminderRow, reminder_id)
            return None if row is None else _to_reminder(row)

    async def lease_due(
        self, now: datetime, worker_id: str, limit: int, lease_duration: timedelta
    ) -> tuple[Reminder, ...]:
        async with self._sessions.begin() as session:
            rows = list(
                await session.scalars(
                    select(ReminderRow)
                    .where(
                        ReminderRow.due_at <= now,
                        or_(
                            ReminderRow.status.in_(
                                (ReminderStatus.SCHEDULED.value, ReminderStatus.RETRY_WAIT.value)
                            ),
                            and_(
                                ReminderRow.status == ReminderStatus.LEASED.value,
                                ReminderRow.lease_until < now,
                            ),
                        ),
                    )
                    .order_by(ReminderRow.due_at, ReminderRow.reminder_id)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            )
            values = tuple(_to_reminder(row) for row in rows)
            for value, row in zip(values, rows, strict=True):
                value.lease(worker_id, now, lease_duration)
                for field, field_value in _values(value).items():
                    if field != "reminder_id":
                        setattr(row, field, field_value)
            return values

    async def save(self, value: Reminder) -> None:
        async with self._sessions.begin() as session:
            row = await session.get(ReminderRow, value.reminder_id, with_for_update=True)
            if row is None:
                raise LookupError("Reminder does not exist")
            for field, field_value in _values(value).items():
                if field != "reminder_id":
                    setattr(row, field, field_value)

    async def list_for_entry(self, entry_id: UUID) -> tuple[Reminder, ...]:
        async with self._sessions() as session:
            rows = await session.scalars(
                select(ReminderRow).where(ReminderRow.agenda_entry_id == entry_id)
            )
            return tuple(_to_reminder(row) for row in rows)


def _values(value: Reminder) -> dict[str, object]:
    return {
        "reminder_id": value.reminder_id,
        "agenda_entry_id": value.agenda_entry_id,
        "agenda_entry_version": value.agenda_entry_version,
        "due_at": value.due_at,
        "idempotency_key": value.idempotency_key,
        "status": value.status.value,
        "attempt_count": value.attempt_count,
        "max_attempts": value.max_attempts,
        "lease_owner": value.lease_owner,
        "lease_until": value.lease_until,
        "delivery_ref": value.delivery_ref,
        "failure_class": value.failure_class,
        "occurrence": value.occurrence,
    }


def _to_reminder(row: ReminderRow) -> Reminder:
    return Reminder(
        row.reminder_id,
        row.agenda_entry_id,
        row.agenda_entry_version,
        row.due_at,
        row.idempotency_key,
        ReminderStatus(row.status),
        row.attempt_count,
        row.max_attempts,
        row.lease_owner,
        row.lease_until,
        row.delivery_ref,
        row.failure_class,
        row.occurrence,
    )
