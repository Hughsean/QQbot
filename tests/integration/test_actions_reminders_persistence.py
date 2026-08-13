from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.sql.elements import ColumnElement

from qq_time_agent.adapters.outbound.persistence.database import create_database_engine
from qq_time_agent.bootstrap.settings import load_runtime_config
from qq_time_agent.modules.actions.application.service import ActionService
from qq_time_agent.modules.actions.infrastructure.repository import SqlActionRepository
from qq_time_agent.modules.actions.infrastructure.tables import ActionRow
from qq_time_agent.modules.agenda.application.service import AgendaService
from qq_time_agent.modules.agenda.infrastructure.repository import SqlAgendaRepository
from qq_time_agent.modules.agenda.infrastructure.tables import AgendaEntryRow
from qq_time_agent.modules.reminders.application.service import ReminderService
from qq_time_agent.modules.reminders.infrastructure.repository import SqlReminderRepository
from qq_time_agent.modules.reminders.infrastructure.tables import ReminderRow
from qq_time_agent.modules.scheduling.contracts import ProposalSlot, SchedulingProposalView

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@dataclass
class Clock:
    value: datetime

    def now(self) -> datetime:
        return self.value


@pytest_asyncio.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    value = create_database_engine(load_runtime_config().database)
    yield value
    await value.dispose()


async def test_action_agenda_reminder_are_idempotent_and_lease_recovers(
    engine: AsyncEngine,
) -> None:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    await _clean_synthetic(sessions)
    now = datetime(2026, 8, 20, 6, tzinfo=UTC)
    proposal = _proposal(now)
    reminders = ReminderService(SqlReminderRepository(sessions))
    service = ActionService(
        SqlActionRepository(sessions),
        AgendaService(SqlAgendaRepository(sessions)),
        reminders,
        Clock(now),
    )
    first = await service.execute_confirmed(proposal, 15)
    second = await service.execute_confirmed(proposal, 15)
    assert first == second
    assert first.agenda_entry_id is not None and first.reminder_id is not None
    task_entry = await AgendaService(SqlAgendaRepository(sessions)).get_entry(first.agenda_entry_id)
    assert task_entry is not None and task_entry.kind == "TASK_BLOCK"

    async with sessions() as session:
        assert await _count_where(session, ActionRow, ActionRow.action_id == first.action_id) == 1
        assert (
            await _count_where(
                session,
                AgendaEntryRow,
                AgendaEntryRow.agenda_entry_id == first.agenda_entry_id,
            )
            == 1
        )
        assert (
            await _count_where(session, ReminderRow, ReminderRow.reminder_id == first.reminder_id)
            == 1
        )

    due = now + timedelta(minutes=45)
    lease_a = (await reminders.lease_due(due, "worker-a", 10, timedelta(minutes=1)))[0]
    assert (
        await reminders.lease_due(due + timedelta(seconds=30), "worker-b", 10, timedelta(minutes=1))
        == ()
    )
    recovered = (
        await ReminderService(SqlReminderRepository(sessions)).lease_due(
            due + timedelta(minutes=2), "worker-b", 10, timedelta(minutes=1)
        )
    )[0]
    assert recovered.reminder_id == lease_a.reminder_id
    assert recovered.attempt_count == 2

    await _clean_synthetic(sessions)


async def test_fixed_event_undo_cancels_agenda_and_old_reminder(engine: AsyncEngine) -> None:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    await _clean_synthetic(sessions)
    now = datetime(2026, 8, 20, 6, tzinfo=UTC)
    reminders = ReminderService(SqlReminderRepository(sessions))
    agenda = AgendaService(SqlAgendaRepository(sessions))
    service = ActionService(SqlActionRepository(sessions), agenda, reminders, Clock(now))
    event = _proposal(now, kind="EVENT")
    result = await service.execute_confirmed(event, 15)
    assert result.agenda_entry_id is not None
    entry = await agenda.get_entry(result.agenda_entry_id)
    assert entry is not None and entry.kind == "EVENT"
    undo = await service.request_undo("owner", entry.agenda_entry_id, entry.version)
    cancelled = await service.confirm_undo("owner", undo.action_id, undo.confirmation_token)
    assert cancelled.agenda_entry_version == 2
    stored = await agenda.get_entry(entry.agenda_entry_id)
    assert stored is not None and stored.status == "CANCELLED"
    assert (
        await reminders.lease_due(now + timedelta(days=1), "worker", 10, timedelta(minutes=1)) == ()
    )
    await _clean_synthetic(sessions)


async def _count(session: AsyncSession, table: type[object]) -> int:
    value = await session.scalar(select(func.count()).select_from(table))
    assert value is not None
    return int(value)


async def _count_where(
    session: AsyncSession, table: type[object], condition: ColumnElement[bool]
) -> int:
    value = await session.scalar(select(func.count()).select_from(table).where(condition))
    assert value is not None
    return int(value)


def _proposal(now: datetime, kind: str = "TASK") -> SchedulingProposalView:
    start = now + timedelta(hours=1)
    return SchedulingProposalView(
        uuid4(),
        2,
        "owner",
        uuid4(),
        kind,
        "Stage 6 integration",
        ProposalSlot(start, start + timedelta(hours=1), "Asia/Shanghai"),
        (),
        (),
        "hard constraints satisfied",
        (),
        ("inbox:stage6",),
        now + timedelta(days=1),
        "CONFIRMED",
    )


async def _clean_synthetic(sessions: async_sessionmaker[AsyncSession]) -> None:
    async with sessions.begin() as session:
        rows = tuple(
            await session.scalars(
                select(AgendaEntryRow).where(AgendaEntryRow.title == "Stage 6 integration")
            )
        )
        entry_ids = [row.agenda_entry_id for row in rows]
        action_ids = [row.action_id for row in rows]
        if entry_ids:
            await session.execute(
                delete(ReminderRow).where(ReminderRow.agenda_entry_id.in_(entry_ids))
            )
            await session.execute(
                delete(AgendaEntryRow).where(AgendaEntryRow.agenda_entry_id.in_(entry_ids))
            )
        if action_ids:
            await session.execute(delete(ActionRow).where(ActionRow.action_id.in_(action_ids)))
