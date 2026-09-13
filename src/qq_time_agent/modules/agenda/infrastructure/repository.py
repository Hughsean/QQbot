"""PostgreSQL idempotent Agenda repository."""

from datetime import datetime
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from qq_time_agent.adapters.outbound.persistence.outbox import SqlOutbox
from qq_time_agent.contracts.clock import Clock
from qq_time_agent.contracts.events import EventEnvelope
from qq_time_agent.modules.agenda.contracts import AGENDA_CHANGED_EVENT, AgendaDraft
from qq_time_agent.modules.agenda.domain.models import AgendaEntry, AgendaStatus
from qq_time_agent.modules.agenda.infrastructure.tables import AgendaEntryRow


class SqlAgendaRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], clock: Clock) -> None:
        self._sessions = sessions
        self._clock = clock

    async def create(self, entry: AgendaEntry, idempotency_key: str) -> AgendaEntry:
        values = _values(entry, idempotency_key)
        async with self._sessions.begin() as session:
            result = await session.execute(
                insert(AgendaEntryRow)
                .values(**values)
                .on_conflict_do_nothing(constraint="uq_agenda_idempotency")
                .returning(AgendaEntryRow.agenda_entry_id)
            )
            inserted = result.scalar_one_or_none()
            row = await session.scalar(
                select(AgendaEntryRow).where(AgendaEntryRow.idempotency_key == idempotency_key)
            )
            if row is None:
                raise RuntimeError("idempotent Agenda create lost stored entry")
            if inserted is not None:
                SqlOutbox.append(session, _changed_event(_to_entry(row), self._clock.now()))
            return _to_entry(row)

    async def get(self, entry_id: UUID) -> AgendaEntry | None:
        async with self._sessions() as session:
            row = await session.get(AgendaEntryRow, entry_id)
            return None if row is None else _to_entry(row)

    async def find_active_by_title(self, title: str) -> tuple[AgendaEntry, ...]:
        async with self._sessions() as session:
            rows = await session.scalars(
                select(AgendaEntryRow)
                .where(
                    AgendaEntryRow.status == AgendaStatus.ACTIVE.value,
                    AgendaEntryRow.title == title,
                )
                .order_by(AgendaEntryRow.starts_at, AgendaEntryRow.agenda_entry_id)
            )
            return tuple(_to_entry(row) for row in rows)

    async def busy_between(
        self, range_start: datetime, range_end: datetime
    ) -> tuple[AgendaEntry, ...]:
        async with self._sessions() as session:
            rows = await session.scalars(
                select(AgendaEntryRow)
                .where(
                    AgendaEntryRow.status == AgendaStatus.ACTIVE.value,
                    AgendaEntryRow.starts_at < range_end,
                    AgendaEntryRow.ends_at > range_start,
                )
                .order_by(AgendaEntryRow.starts_at, AgendaEntryRow.agenda_entry_id)
            )
            return tuple(_to_entry(row) for row in rows)

    async def list_active_page(
        self, after_entry_id: UUID | None, limit: int
    ) -> tuple[AgendaEntry, ...]:
        async with self._sessions() as session:
            statement = select(AgendaEntryRow).where(
                AgendaEntryRow.status == AgendaStatus.ACTIVE.value
            )
            if after_entry_id is not None:
                statement = statement.where(AgendaEntryRow.agenda_entry_id > after_entry_id)
            rows = await session.scalars(
                statement.order_by(AgendaEntryRow.agenda_entry_id).limit(limit)
            )
            return tuple(_to_entry(row) for row in rows)

    async def find_by_source_ref(self, source_ref: str) -> AgendaEntry | None:
        async with self._sessions() as session:
            row = await session.scalar(
                select(AgendaEntryRow)
                .where(AgendaEntryRow.source_refs.contains([source_ref]))
                .order_by(AgendaEntryRow.agenda_entry_id)
                .limit(1)
            )
            return None if row is None else _to_entry(row)

    async def save(
        self, entry: AgendaEntry, expected_version: int, idempotency_key: str
    ) -> AgendaEntry:
        if not idempotency_key.strip():
            raise ValueError("Agenda idempotency key is required")
        async with self._sessions.begin() as session:
            existing = await session.get(AgendaEntryRow, entry.agenda_entry_id)
            if existing is not None and existing.last_operation_key == idempotency_key:
                return _to_entry(existing)
            values = _values(entry, idempotency_key)
            values.pop("agenda_entry_id")
            result = await session.execute(
                update(AgendaEntryRow)
                .where(
                    AgendaEntryRow.agenda_entry_id == entry.agenda_entry_id,
                    AgendaEntryRow.version == expected_version,
                )
                .values(**values)
            )
            if cast("CursorResult[tuple[()]]", result).rowcount != 1:
                raise RuntimeError("Agenda entry version conflict")
            SqlOutbox.append(session, _changed_event(entry, self._clock.now()))
            return entry


def _values(value: AgendaEntry, idempotency_key: str) -> dict[str, object]:
    return {
        "agenda_entry_id": value.agenda_entry_id,
        "action_id": value.action_id,
        "idempotency_key": idempotency_key,
        "kind": value.draft.kind,
        "title": value.draft.title,
        "starts_at": value.draft.starts_at,
        "ends_at": value.draft.ends_at,
        "timezone": value.draft.timezone,
        "status": value.status.value,
        "source_refs": list(value.draft.source_refs),
        "proposal_id": value.draft.proposal_id,
        "version": value.version,
        "last_operation_key": idempotency_key,
    }


def _to_entry(row: AgendaEntryRow) -> AgendaEntry:
    return AgendaEntry(
        row.agenda_entry_id,
        row.action_id,
        AgendaDraft(
            row.kind,
            row.title,
            row.starts_at,
            row.ends_at,
            row.timezone,
            tuple(row.source_refs),
            row.proposal_id,
        ),
        AgendaStatus(row.status),
        row.version,
    )


def _changed_event(entry: AgendaEntry, occurred_at: datetime) -> EventEnvelope:
    return EventEnvelope(
        uuid4(),
        AGENDA_CHANGED_EVENT,
        1,
        f"agenda:{entry.agenda_entry_id}",
        {
            "agenda_entry_id": str(entry.agenda_entry_id),
            "agenda_entry_version": entry.version,
            "status": entry.status.value,
        },
        occurred_at,
    )
