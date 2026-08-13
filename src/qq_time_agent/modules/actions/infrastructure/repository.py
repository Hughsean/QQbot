"""PostgreSQL idempotent ActionRequest repository."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from qq_time_agent.modules.actions.domain.models import (
    ActionRequest,
    ActionStatus,
    ActionType,
)
from qq_time_agent.modules.actions.infrastructure.tables import ActionRow


class SqlActionRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def add(self, value: ActionRequest) -> ActionRequest:
        async with self._sessions.begin() as session:
            await session.execute(
                insert(ActionRow)
                .values(**_values(value))
                .on_conflict_do_nothing(constraint="uq_actions_idempotency")
            )
            row = await session.scalar(
                select(ActionRow).where(ActionRow.idempotency_key == value.idempotency_key)
            )
            if row is None:
                raise RuntimeError("idempotent Action insert lost stored row")
            return _to_action(row)

    async def get(self, action_id: UUID) -> ActionRequest | None:
        async with self._sessions() as session:
            row = await session.get(ActionRow, action_id)
            return None if row is None else _to_action(row)

    async def save(self, value: ActionRequest) -> None:
        async with self._sessions.begin() as session:
            row = await session.get(ActionRow, value.action_id, with_for_update=True)
            if row is None:
                raise LookupError("Action does not exist")
            for field, field_value in _values(value).items():
                if field != "action_id":
                    setattr(row, field, field_value)


def _values(value: ActionRequest) -> dict[str, object]:
    return {
        "action_id": value.action_id,
        "user_id": value.user_id,
        "action_type": value.action_type.value,
        "idempotency_key": value.idempotency_key,
        "status": value.status.value,
        "requested_at": value.requested_at,
        "proposal_id": value.proposal_id,
        "proposal_version": value.proposal_version,
        "agenda_entry_id": value.agenda_entry_id,
        "agenda_entry_version": value.agenda_entry_version,
        "reminder_id": value.reminder_id,
        "failure_class": value.failure_class,
    }


def _to_action(row: ActionRow) -> ActionRequest:
    return ActionRequest(
        row.action_id,
        row.user_id,
        ActionType(row.action_type),
        row.idempotency_key,
        ActionStatus(row.status),
        row.requested_at,
        row.proposal_id,
        row.proposal_version,
        row.agenda_entry_id,
        row.agenda_entry_version,
        row.reminder_id,
        row.failure_class,
    )
