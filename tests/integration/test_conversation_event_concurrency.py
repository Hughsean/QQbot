from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from qq_time_agent.adapters.outbound.persistence.database import create_database_engine
from qq_time_agent.bootstrap.settings import load_runtime_config
from qq_time_agent.modules.agent.contracts import (
    ConversationEvent,
    ConversationEventType,
    ConversationScopeType,
)
from qq_time_agent.modules.agent.infrastructure.conversation_events import (
    SqlConversationEventRepository,
)
from qq_time_agent.modules.agent.infrastructure.tables import (
    ConversationEventRow,
    ConversationSequenceRow,
)

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def engine() -> AsyncEngine:
    engine = create_database_engine(load_runtime_config().database)
    yield engine
    await engine.dispose()


def _event(user_id: str, scope_id, key: str) -> ConversationEvent:
    return ConversationEvent(
        ConversationScopeType.CONVERSATION,
        scope_id,
        user_id,
        ConversationEventType.USER_MESSAGE,
        datetime.now(UTC),
        f"synthetic-{key}",
        key,
        inbox_item_id=uuid4(),
    )


@pytest.mark.asyncio
async def test_concurrent_append_allocates_unique_contiguous_sequences(
    engine: AsyncEngine,
) -> None:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    repository = SqlConversationEventRepository(sessions)
    user_id = f"concurrent-{uuid4()}"
    scope_id = uuid4()
    try:
        events = [_event(user_id, scope_id, f"key-{index}") for index in range(12)]
        stored = await asyncio.gather(
            *(repository.append(item, datetime.now(UTC)) for item in events)
        )
        sequences = sorted(item.sequence for item in stored)
        assert sequences == list(range(1, 13))
        assert len({item.event_id for item in stored}) == 12
    finally:
        async with sessions.begin() as session:
            await session.execute(
                delete(ConversationEventRow).where(
                    ConversationEventRow.user_id == user_id
                )
            )
            await session.execute(
                delete(ConversationSequenceRow).where(
                    ConversationSequenceRow.user_id == user_id
                )
            )


@pytest.mark.asyncio
async def test_concurrent_same_idempotency_key_returns_one_event(
    engine: AsyncEngine,
) -> None:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    repository = SqlConversationEventRepository(sessions)
    user_id = f"idempotent-{uuid4()}"
    scope_id = uuid4()
    try:
        event = _event(user_id, scope_id, "same-key")
        stored = await asyncio.gather(
            *(repository.append(event, datetime.now(UTC)) for _ in range(8))
        )
        assert len({item.event_id for item in stored}) == 1
        assert len({item.sequence for item in stored}) == 1
        assert await repository.current_sequence(user_id) == 1
    finally:
        async with sessions.begin() as session:
            await session.execute(
                delete(ConversationEventRow).where(
                    ConversationEventRow.user_id == user_id
                )
            )
            await session.execute(
                delete(ConversationSequenceRow).where(
                    ConversationSequenceRow.user_id == user_id
                )
            )
