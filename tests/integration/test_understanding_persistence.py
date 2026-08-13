from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from qq_time_agent.adapters.outbound.persistence.database import create_database_engine
from qq_time_agent.bootstrap.settings import load_runtime_config
from qq_time_agent.modules.ai_gateway.application.ports import InvocationMetadata
from qq_time_agent.modules.ai_gateway.infrastructure.repository import SqlInvocationRepository
from qq_time_agent.modules.ai_gateway.infrastructure.tables import ModelInvocationRow
from qq_time_agent.modules.understanding.contracts import CandidateKind
from qq_time_agent.modules.understanding.domain.candidates import Candidate
from qq_time_agent.modules.understanding.infrastructure.repository import SqlCandidateRepository
from qq_time_agent.modules.understanding.infrastructure.tables import CandidateRow
from qq_time_agent.modules.workflow.application.ports import WorkflowCheckpoint
from qq_time_agent.modules.workflow.infrastructure.repository import (
    SqlWorkflowCheckpointRepository,
)
from qq_time_agent.modules.workflow.infrastructure.tables import UnderstandingCheckpointRow

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest_asyncio.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    value = create_database_engine(load_runtime_config().database)
    yield value
    await value.dispose()


async def test_stage4_owned_tables_are_idempotent_and_content_free(
    engine: AsyncEngine,
) -> None:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    inbox_item_id = uuid4()
    candidate = Candidate.create(
        inbox_item_id,
        CandidateKind.EVENT,
        "Review plan",
        datetime(2026, 8, 19, 7, tzinfo=UTC),
        datetime(2026, 8, 19, 8, tzinfo=UTC),
        None,
        "Asia/Shanghai",
        None,
        (),
        60,
        "NORMAL",
        (),
        0.9,
        (),
        ("Review plan",),
        (f"inbox:{inbox_item_id}:hash",),
    )
    candidates = SqlCandidateRepository(sessions)
    first = await candidates.add(candidate)
    duplicate = await candidates.add(
        Candidate.create(
            inbox_item_id,
            CandidateKind.EVENT,
            "Concurrent duplicate",
            datetime(2026, 8, 19, 7, tzinfo=UTC),
            datetime(2026, 8, 19, 8, tzinfo=UTC),
            None,
            "Asia/Shanghai",
            None,
            (),
            60,
            "NORMAL",
            (),
            0.9,
            (),
            ("Concurrent duplicate",),
            (f"inbox:{inbox_item_id}:hash",),
        )
    )
    restored = await candidates.get_for_inbox(inbox_item_id)
    assert first == duplicate == restored == candidate

    checkpoints = SqlWorkflowCheckpointRepository(sessions)
    await checkpoints.save(
        WorkflowCheckpoint(
            inbox_item_id, "DECIDED", "EVENT", candidate.candidate_id, 0.9, None, 2, 1
        )
    )
    await checkpoints.save(
        WorkflowCheckpoint(
            inbox_item_id, "COMPLETE", "EVENT", candidate.candidate_id, 0.9, None, 2, 2
        )
    )
    assert (await checkpoints.get(inbox_item_id)).phase == "COMPLETE"  # type: ignore[union-attr]

    now = datetime(2026, 8, 13, tzinfo=UTC)
    invocation_id = uuid4()
    await SqlInvocationRepository(sessions).add(
        InvocationMetadata(
            invocation_id,
            "understanding.classify",
            "v1",
            "FAST",
            "model",
            "SUCCEEDED",
            None,
            10,
            5,
            now,
            now + timedelta(milliseconds=20),
            20,
        )
    )
    async with sessions() as session:
        count = await session.scalar(select(func.count()).select_from(CandidateRow))
        assert count is not None and count >= 1
        invocation = await session.get(ModelInvocationRow, invocation_id)
        assert invocation is not None
        assert not hasattr(invocation, "prompt") and not hasattr(invocation, "content")

    async with sessions.begin() as session:
        await session.execute(
            delete(UnderstandingCheckpointRow).where(
                UnderstandingCheckpointRow.inbox_item_id == inbox_item_id
            )
        )
        await session.execute(
            delete(CandidateRow).where(CandidateRow.inbox_item_id == inbox_item_id)
        )
        await session.execute(
            delete(ModelInvocationRow).where(ModelInvocationRow.invocation_id == invocation_id)
        )
