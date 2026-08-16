from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from qq_time_agent.adapters.outbound.persistence.database import create_database_engine
from qq_time_agent.bootstrap.settings import load_runtime_config
from qq_time_agent.modules.agenda.application.service import AgendaService
from qq_time_agent.modules.agenda.application.source_lookup import AgendaSourceLookupService
from qq_time_agent.modules.agenda.contracts import AgendaDraft
from qq_time_agent.modules.agenda.infrastructure.repository import SqlAgendaRepository
from qq_time_agent.modules.agenda.infrastructure.tables import AgendaEntryRow
from qq_time_agent.modules.scheduling.contracts import ProposalSlot
from qq_time_agent.modules.scheduling.domain.models import SchedulingProposal
from qq_time_agent.modules.scheduling.infrastructure.repository import SqlProposalRepository
from qq_time_agent.modules.scheduling.infrastructure.tables import ProposalRow

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest_asyncio.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    value = create_database_engine(load_runtime_config().database)
    yield value
    await value.dispose()


async def test_agenda_is_idempotent_fact_source_and_busy_query_is_overlap_safe(
    engine: AsyncEngine,
) -> None:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    repository = SqlAgendaRepository(sessions)
    service = AgendaService(repository)
    proposal_id = uuid4()
    action_id = uuid4()
    start = datetime(2026, 8, 20, 7, tzinfo=UTC)
    draft = AgendaDraft(
        "EVENT",
        "Stage 5 integration",
        start,
        start + timedelta(hours=1),
        "Asia/Shanghai",
        ("inbox:integration", "calendar:" + "a" * 64),
        proposal_id,
    )
    first = await service.create_entry(action_id, draft, f"agenda-test-{proposal_id}")
    second = await service.create_entry(uuid4(), draft, f"agenda-test-{proposal_id}")
    assert first == second
    matched = await AgendaSourceLookupService(repository).find_by_source_ref("calendar:" + "a" * 64)
    assert matched is not None and matched.agenda_entry_id == first.agenda_entry_id
    busy = await service.get_busy_intervals(
        start + timedelta(minutes=30), start + timedelta(hours=2)
    )
    assert len(busy) == 1 and busy[0].agenda_entry_id == first.agenda_entry_id
    assert (
        await service.get_busy_intervals(start - timedelta(hours=2), start - timedelta(hours=1))
        == ()
    )

    async with sessions.begin() as session:
        await session.execute(
            delete(AgendaEntryRow).where(AgendaEntryRow.agenda_entry_id == first.agenda_entry_id)
        )


async def test_proposal_insert_is_idempotent_and_restores_constraint_snapshot(
    engine: AsyncEngine,
) -> None:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    repository = SqlProposalRepository(sessions)
    candidate_id = uuid4()
    start = datetime(2026, 8, 20, 7, tzinfo=UTC)
    proposal = SchedulingProposal.create(
        "owner",
        candidate_id,
        "TASK",
        "Write report",
        ProposalSlot(start, start + timedelta(hours=1), "Asia/Shanghai"),
        (),
        (),
        "hard constraints satisfied",
        (),
        ("inbox:integration",),
        start + timedelta(days=1),
        {"grid_minutes": 15, "timezone": "Asia/Shanghai"},
    )
    first = await repository.add(proposal)
    duplicate = await repository.add(
        SchedulingProposal.create(
            "owner",
            candidate_id,
            "TASK",
            "Different transient value",
            proposal.recommended_slot,
            (),
            (),
            "should not replace",
            (),
            proposal.source_refs,
            proposal.expires_at,
            proposal.constraint_snapshot,
        )
    )
    assert first == duplicate == await repository.get(first.proposal_id)
    assert first.constraint_snapshot["grid_minutes"] == 15
    async with sessions() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(ProposalRow)
            .where(ProposalRow.candidate_id == candidate_id)
        )
        assert count == 1
    async with sessions.begin() as session:
        await session.execute(delete(ProposalRow).where(ProposalRow.candidate_id == candidate_id))
