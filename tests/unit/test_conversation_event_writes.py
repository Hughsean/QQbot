"""AgentRunService conversation event write behaviour (USER_MESSAGE)."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from qq_time_agent.contracts.tools import ToolDefinition
from qq_time_agent.modules.agent.application.loop import AgentLoop
from qq_time_agent.modules.agent.application.run_service import AgentRunService
from qq_time_agent.modules.agent.contracts import (
    AgentResponse,
    AgentRun,
    AgentRunStatus,
    ContextScope,
    ConversationEvent,
    ConversationEventType,
    ConversationEventView,
    ConversationScopeType,
)

NOW = datetime(2026, 8, 27, 10, tzinfo=UTC)


class Clock:
    def now(self) -> datetime:
        return NOW


@dataclass
class Model:
    async def respond(self, request: object) -> AgentResponse:
        del request
        raise AssertionError("ensure_run must not execute the model")


@dataclass
class Tools:
    def definitions(self) -> tuple[ToolDefinition, ...]:
        return ()

    async def call(
        self, owner_id: str, name: str, arguments: dict[str, object], context: object
    ) -> object:
        del owner_id, name, arguments, context
        raise AssertionError("ensure_run must not call tools")


@dataclass
class Repository:
    run: AgentRun
    conversation_id: UUID | None
    attached: list[UUID] = field(default_factory=list)

    async def ensure_scope(
        self, user_id: str, conversation_key: str | None, event_key: str | None, now: datetime
    ) -> ContextScope:
        del user_id, conversation_key, event_key, now
        return ContextScope(self.conversation_id, None)

    async def attach_item(
        self, scope: ContextScope, inbox_item_id: UUID, occurred_at: datetime
    ) -> None:
        del scope, occurred_at
        self.attached.append(inbox_item_id)

    async def get_or_create(
        self,
        inbox_item_id: UUID,
        user_id: str,
        source_type: str,
        now: datetime,
        scope: ContextScope | None = None,
        source_refs: tuple[str, ...] = (),
    ) -> AgentRun:
        del user_id, source_type, now, source_refs
        self.run.inbox_item_id = inbox_item_id
        self.run.conversation_id = None if scope is None else scope.conversation_id
        return self.run


@dataclass
class Timeline:
    events: list[ConversationEvent] = field(default_factory=list)
    failure: Exception | None = None

    async def append(self, event: ConversationEvent, now: datetime) -> ConversationEventView:
        del now
        if self.failure is not None:
            raise self.failure
        self.events.append(event)
        return ConversationEventView(
            event.event_id,
            event.scope_type,
            event.scope_id,
            event.user_id,
            len(self.events),
            event.event_type,
            event.role,
            event.occurred_at,
            event.occurred_at,
            event.content,
            event.content_ref,
            event.content_hash,
            event.delivery_status,
            event.run_id,
            event.inbox_item_id,
            event.notification_intent_id,
            event.idempotency_key,
            dict(event.metadata),
        )


def _service(repository: Repository, timeline: Timeline) -> AgentRunService:
    loop = AgentLoop(Model(), Tools())  # type: ignore[arg-type]
    return AgentRunService(repository, loop, Clock(), timeline=timeline)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_ensure_run_records_user_message_event_once_per_item() -> None:
    run = AgentRun(uuid4(), uuid4(), "owner", "QQ_DIRECT", AgentRunStatus.PENDING, 0)
    conversation_id = uuid4()
    repository = Repository(run, conversation_id)
    timeline = Timeline()
    service = _service(repository, timeline)

    item = uuid4()
    await service.ensure_run(
        item, "owner", "QQ_DIRECT", conversation_key="owner", occurred_at=NOW, message="继续"
    )
    await service.ensure_run(
        item, "owner", "QQ_DIRECT", conversation_key="owner", occurred_at=NOW, message="继续"
    )

    assert len(timeline.events) == 2
    keys = {event.idempotency_key for event in timeline.events}
    assert keys == {f"user-message:{item}"}
    event = timeline.events[0]
    assert event.event_type is ConversationEventType.USER_MESSAGE
    assert event.scope_type is ConversationScopeType.CONVERSATION
    assert event.scope_id == conversation_id
    assert event.content == "继续"
    assert event.inbox_item_id == item
    assert event.content_ref == f"inbox:{item}"
    assert event.metadata == {"source_type": "QQ_DIRECT"}
    assert repository.attached == [item, item]


@pytest.mark.asyncio
async def test_ensure_run_skips_user_message_without_content_or_scope() -> None:
    run = AgentRun(uuid4(), uuid4(), "owner", "QQ_DIRECT", AgentRunStatus.PENDING, 0)
    timeline = Timeline()
    service = _service(Repository(run, uuid4()), timeline)

    await service.ensure_run(
        uuid4(), "owner", "QQ_DIRECT", conversation_key="owner", occurred_at=NOW
    )
    await service.ensure_run(uuid4(), "owner", "QQ_DIRECT", occurred_at=NOW, message="内容")
    await service.ensure_run(
        uuid4(), "owner", "QQ_DIRECT", conversation_key="owner", occurred_at=NOW, message="  "
    )

    assert timeline.events == []


@pytest.mark.asyncio
async def test_ensure_run_bounds_oversized_user_message_content() -> None:
    run = AgentRun(uuid4(), uuid4(), "owner", "QQ_DIRECT", AgentRunStatus.PENDING, 0)
    timeline = Timeline()
    service = _service(Repository(run, uuid4()), timeline)

    await service.ensure_run(
        uuid4(),
        "owner",
        "QQ_DIRECT",
        conversation_key="owner",
        occurred_at=NOW,
        message="长" * 12_500,
    )

    assert len(timeline.events) == 1
    assert len(timeline.events[0].content) == 12_000


@pytest.mark.asyncio
async def test_ensure_run_survives_timeline_failure() -> None:
    run = AgentRun(uuid4(), uuid4(), "owner", "QQ_DIRECT", AgentRunStatus.PENDING, 0)
    timeline = Timeline(failure=RuntimeError("timeline unavailable"))
    service = _service(Repository(run, uuid4()), timeline)

    ensured = await service.ensure_run(
        uuid4(), "owner", "QQ_DIRECT", conversation_key="owner", occurred_at=NOW, message="继续"
    )

    assert ensured.run_id == run.run_id
