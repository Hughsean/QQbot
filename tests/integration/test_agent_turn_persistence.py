from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from qq_time_agent.adapters.outbound.persistence.database import create_database_engine
from qq_time_agent.bootstrap.settings import load_runtime_config
from qq_time_agent.modules.agent.contracts import TurnClaimDecision
from qq_time_agent.modules.agent.infrastructure.tables import (
    AgentTurnBatchRow,
    AgentTurnSegmentRow,
)
from qq_time_agent.modules.agent.infrastructure.turns import SqlAgentTurnRepository

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def engine() -> AsyncEngine:
    value = create_database_engine(load_runtime_config().database)
    yield value
    await value.dispose()


def _stage(repository: SqlAgentTurnRepository, item_id: UUID, now: datetime, sequence: int):
    return repository.stage(
        user_id="synthetic-owner",
        conversation_key_hash="a" * 64,
        inbox_item_id=item_id,
        source_type="QQ_DIRECT",
        trust_level="T1",
        occurred_at=now,
        provider_sequence=sequence,
        reference_hash=None,
        content_chars=10,
        now=now,
        quiet_seconds=1.2,
        max_batch_seconds=4.0,
        max_messages=8,
        max_chars=12_000,
    )


@pytest.mark.asyncio
async def test_new_message_supersedes_waiter_and_claim_preserves_order(
    engine: AsyncEngine,
) -> None:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    repository = SqlAgentTurnRepository(sessions)
    now = datetime.now(UTC)
    first_id, second_id = uuid4(), uuid4()
    first = await _stage(repository, first_id, now, 20)
    second = await _stage(repository, second_id, now + timedelta(milliseconds=500), 21)
    try:
        stale = await repository.try_claim(
            first, "waiter-1", now + timedelta(seconds=2), now + timedelta(minutes=5)
        )
        assert stale.decision is TurnClaimDecision.SUPERSEDED

        claimed = await repository.try_claim(
            second, "waiter-2", now + timedelta(seconds=2), now + timedelta(minutes=5)
        )
        assert claimed.decision is TurnClaimDecision.CLAIMED
        assert claimed.claim is not None
        assert [item.inbox_item_id for item in claimed.claim.segments] == [
            first_id,
            second_id,
        ]
        await repository.complete(claimed.claim, now + timedelta(seconds=3))
    finally:
        await _clean(sessions, (first.turn_id,))


@pytest.mark.asyncio
async def test_later_batch_waits_until_same_conversation_turn_completes(
    engine: AsyncEngine,
) -> None:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    repository = SqlAgentTurnRepository(sessions)
    now = datetime.now(UTC)
    first = await repository.stage(
        user_id="synthetic-owner",
        conversation_key_hash="b" * 64,
        inbox_item_id=uuid4(),
        source_type="QQ_DIRECT",
        trust_level="T1",
        occurred_at=now,
        provider_sequence=1,
        reference_hash=None,
        content_chars=10,
        now=now,
        quiet_seconds=0.1,
        max_batch_seconds=4.0,
        max_messages=1,
        max_chars=12_000,
    )
    second = await repository.stage(
        user_id="synthetic-owner",
        conversation_key_hash="b" * 64,
        inbox_item_id=uuid4(),
        source_type="QQ_DIRECT",
        trust_level="T1",
        occurred_at=now + timedelta(milliseconds=10),
        provider_sequence=2,
        reference_hash=None,
        content_chars=10,
        now=now + timedelta(milliseconds=10),
        quiet_seconds=0.1,
        max_batch_seconds=4.0,
        max_messages=1,
        max_chars=12_000,
    )
    try:
        at = now + timedelta(seconds=1)
        blocked = await repository.try_claim(second, "second", at, at + timedelta(minutes=5))
        assert blocked.decision is TurnClaimDecision.WAIT
        first_claim = await repository.try_claim(first, "first", at, at + timedelta(minutes=5))
        assert first_claim.claim is not None
        await repository.complete(first_claim.claim, at + timedelta(milliseconds=10))
        second_claim = await repository.try_claim(
            second, "second", at + timedelta(milliseconds=20), at + timedelta(minutes=5)
        )
        assert second_claim.decision is TurnClaimDecision.CLAIMED
    finally:
        await _clean(sessions, (first.turn_id, second.turn_id))


async def _clean(sessions, turn_ids: tuple[UUID, ...]) -> None:
    async with sessions.begin() as session:
        await session.execute(
            delete(AgentTurnSegmentRow).where(AgentTurnSegmentRow.turn_id.in_(turn_ids))
        )
        await session.execute(
            delete(AgentTurnBatchRow).where(AgentTurnBatchRow.turn_id.in_(turn_ids))
        )
