import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from qq_time_agent.adapters.outbound.persistence.database import create_database_engine
from qq_time_agent.bootstrap.settings import load_runtime_config
from qq_time_agent.modules.agent.application.conversation_replay import (
    ConversationTimelineReplay,
)
from qq_time_agent.modules.agent.application.conversation_summary import (
    ConversationSummaryService,
    SummaryRequest,
)
from qq_time_agent.modules.agent.contracts import (
    ConversationEvent,
    ConversationEventType,
    ConversationScopeType,
    ConversationSummaryView,
    ConversationSummaryWrite,
    owner_timeline_scope_id,
    summary_source_hash,
)
from qq_time_agent.modules.agent.infrastructure.conversation_events import (
    SqlConversationEventRepository,
)
from qq_time_agent.modules.agent.infrastructure.tables import (
    ConversationEventRow,
    ConversationSequenceRow,
    ConversationSummaryRow,
)

pytestmark = pytest.mark.integration
NOW = datetime(2026, 9, 11, 12, tzinfo=UTC)


@dataclass(frozen=True)
class FixedClock:
    def now(self) -> datetime:
        return NOW


@pytest_asyncio.fixture
async def engine() -> AsyncEngine:
    value = create_database_engine(load_runtime_config().database)
    yield value
    await value.dispose()


@pytest.mark.asyncio
async def test_replay_and_summary_are_isolated_idempotent_and_snapshot_safe(
    engine: AsyncEngine, tmp_path: Path
) -> None:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    repository = SqlConversationEventRepository(sessions)
    user_a = f"replay-integration-{uuid4()}"
    user_b = f"replay-integration-{uuid4()}"
    conversation_a, conversation_b = uuid4(), uuid4()
    fixture = tmp_path / "timeline.json"
    fixture.write_text(
        json.dumps(_payload(user_a, user_b, conversation_a, conversation_b), ensure_ascii=False),
        encoding="utf-8",
    )
    replay = ConversationTimelineReplay(repository, clock=FixedClock())
    try:
        first = await replay.replay_path(fixture)
        second = await replay.replay_path(fixture)
        assert (first.inserted_count, first.skipped_count) == (5, 0)
        assert (second.inserted_count, second.skipped_count) == (0, 5)
        assert await repository.current_sequence(user_a) == 3
        assert await repository.current_sequence(user_b) == 2

        conversation = await repository.list_timeline(
            user_a, ConversationScopeType.CONVERSATION, conversation_a, limit=10
        )
        owner = await repository.list_timeline(
            user_a,
            ConversationScopeType.OWNER_TIMELINE,
            owner_timeline_scope_id(user_a),
            limit=10,
        )
        assert [item.sequence for item in conversation] == [1, 3]
        assert [item.sequence for item in owner] == [2]

        snapshot = await repository.create_snapshot(user_a, conversation_a)
        await repository.append(_after_snapshot(user_a, conversation_a), NOW)
        visible = await repository.list_snapshot_events(
            user_a,
            ConversationScopeType.CONVERSATION,
            conversation_a,
            max_sequence=snapshot.max_sequence,
            limit=10,
        )
        assert [item.sequence for item in visible] == [1, 3]

        summaries = ConversationSummaryService(repository, FixedClock())
        stored = await summaries.summarize(SummaryRequest(user_a, conversation_a, 1, 3))
        duplicate = await summaries.summarize(SummaryRequest(user_a, conversation_a, 1, 3))
        assert duplicate == stored
        assert await _row_count(sessions, ConversationSummaryRow, user_a) == 1
        assert await _row_count(sessions, ConversationEventRow, user_a) == 4
    finally:
        await _cleanup(sessions, (user_a, user_b))


@pytest.mark.asyncio
async def test_concurrent_overlapping_summaries_serialize_per_scope(
    engine: AsyncEngine,
) -> None:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    repository = SqlConversationEventRepository(sessions)
    user_id = f"replay-integration-{uuid4()}"
    scope_id = uuid4()
    try:
        await repository.append(_conversation_event(user_id, scope_id, True), NOW)
        await repository.append(_conversation_event(user_id, scope_id, False), NOW)
        source = await repository.list_timeline(
            user_id, ConversationScopeType.CONVERSATION, scope_id, limit=10
        )
        source_hash = summary_source_hash(source)
        requests = tuple(
            ConversationSummaryWrite(
                ConversationSummaryView(
                    uuid4(),
                    user_id,
                    ConversationScopeType.CONVERSATION,
                    scope_id,
                    1,
                    2,
                    "并发摘要",
                    NOW,
                    source_hash=source_hash,
                    idempotency_key=f"summary-overlap:{uuid4()}",
                ),
                source,
            )
            for _ in range(2)
        )

        results = await asyncio.gather(
            *(repository.write_summary(request) for request in requests),
            return_exceptions=True,
        )

        assert sum(isinstance(item, ConversationSummaryView) for item in results) == 1
        assert sum(isinstance(item, ValueError) for item in results) == 1
        assert await _row_count(sessions, ConversationSummaryRow, user_id) == 1
    finally:
        await _cleanup(sessions, (user_id,))


def _payload(
    user_a: str, user_b: str, conversation_a: UUID, conversation_b: UUID
) -> dict[str, object]:
    notification_id = uuid4()
    return {
        "version": 1,
        "redacted": True,
        "events": [
            _row(user_a, conversation_a, 1, "USER_MESSAGE", "user", "需求", "a:user"),
            {
                **_row(
                    user_a,
                    owner_timeline_scope_id(user_a),
                    2,
                    "DAILY_DIGEST",
                    "system",
                    "脱敏摘要",
                    "a:digest",
                ),
                "scope_type": "owner_timeline",
                "notification_intent_id": str(notification_id),
                "delivery_status": "DELIVERED",
            },
            _row(user_a, conversation_a, 3, "AGENT_REPLY", "agent", "答复", "a:reply"),
            _row(user_b, conversation_b, 1, "USER_MESSAGE", "user", "问题", "b:user"),
            _row(user_b, conversation_b, 2, "AGENT_REPLY", "agent", "响应", "b:reply"),
        ],
    }


def _row(
    user_id: str,
    scope_id: UUID,
    sequence: int,
    event_type: str,
    role: str,
    content: str,
    key: str,
) -> dict[str, object]:
    return {
        "user_id": user_id,
        "scope_type": "conversation",
        "scope_id": str(scope_id),
        "sequence": sequence,
        "event_type": event_type,
        "role": role,
        "content": content,
        "idempotency_key": f"replay:{uuid4()}:{key}",
    }


def _after_snapshot(user_id: str, scope_id: UUID) -> ConversationEvent:
    return ConversationEvent(
        ConversationScopeType.CONVERSATION,
        scope_id,
        user_id,
        ConversationEventType.USER_MESSAGE,
        NOW + timedelta(seconds=1),
        "快照后消息",
        f"after-snapshot:{uuid4()}",
        inbox_item_id=uuid4(),
    )


def _conversation_event(user_id: str, scope_id: UUID, user_message: bool) -> ConversationEvent:
    event_type = (
        ConversationEventType.USER_MESSAGE if user_message else ConversationEventType.AGENT_REPLY
    )
    return ConversationEvent(
        ConversationScopeType.CONVERSATION,
        scope_id,
        user_id,
        event_type,
        NOW,
        "合成用户消息" if user_message else "合成 Agent 回复",
        f"summary-source:{uuid4()}",
        inbox_item_id=uuid4() if user_message else None,
        run_id=None if user_message else uuid4(),
    )


async def _row_count(sessions, row_type, user_id: str) -> int:
    async with sessions() as session:
        value = await session.scalar(
            select(func.count()).select_from(row_type).where(row_type.user_id == user_id)
        )
    return int(value or 0)


async def _cleanup(sessions, users: tuple[str, ...]) -> None:
    async with sessions.begin() as session:
        await session.execute(
            delete(ConversationSummaryRow).where(ConversationSummaryRow.user_id.in_(users))
        )
        await session.execute(
            delete(ConversationEventRow).where(ConversationEventRow.user_id.in_(users))
        )
        await session.execute(
            delete(ConversationSequenceRow).where(ConversationSequenceRow.user_id.in_(users))
        )
