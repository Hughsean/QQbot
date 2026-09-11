"""Unified timeline context assembly with pinned snapshots."""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from qq_time_agent.modules.agent.application.budget import ContextBudgetPolicy
from qq_time_agent.modules.agent.application.timeline_context import (
    TimelineContext,
    TimelineContextAssembler,
)
from qq_time_agent.modules.agent.contracts import (
    ConversationDeliveryStatus,
    ConversationEventRole,
    ConversationEventType,
    ConversationEventView,
    ConversationScopeType,
    ConversationSnapshot,
    ConversationSummaryView,
    ConversationSummaryWrite,
    snapshot_hash,
    summary_source_hash,
)
from qq_time_agent.modules.ai_gateway.contracts import AgentMessageRole

NOW = datetime(2026, 8, 27, 10, tzinfo=UTC)
CONVERSATION_ID = uuid4()
OWNER_SCOPE = uuid4()

_ROLE = {
    ConversationEventType.USER_MESSAGE: ConversationEventRole.USER,
    ConversationEventType.AGENT_REPLY: ConversationEventRole.AGENT,
    ConversationEventType.TOOL_CALL: ConversationEventRole.TOOL,
    ConversationEventType.TOOL_RESULT: ConversationEventRole.TOOL,
    ConversationEventType.MAIL_NOTIFICATION: ConversationEventRole.SYSTEM,
    ConversationEventType.MAIL_DIGEST: ConversationEventRole.SYSTEM,
    ConversationEventType.DAILY_DIGEST: ConversationEventRole.SYSTEM,
    ConversationEventType.SYSTEM_RESULT: ConversationEventRole.SYSTEM,
}


@dataclass
class Repository:
    conversation: list[ConversationEventView] = field(default_factory=list)
    owner: list[ConversationEventView] = field(default_factory=list)
    summaries: list[ConversationSummaryView] = field(default_factory=list)

    async def create_snapshot(self, user_id: str, scope_id: UUID) -> ConversationSnapshot:
        sequences = [
            item.sequence for item in (*self.conversation, *self.owner) if item.user_id == user_id
        ]
        maximum = max(sequences, default=0)
        return ConversationSnapshot(
            user_id, scope_id, maximum, maximum, snapshot_hash(user_id, scope_id, maximum)
        )

    async def list_snapshot_events(
        self,
        user_id: str,
        scope_type: ConversationScopeType,
        scope_id: UUID,
        *,
        max_sequence: int,
        limit: int,
    ) -> tuple[ConversationEventView, ...]:
        del scope_id
        source = (
            self.conversation if scope_type is ConversationScopeType.CONVERSATION else self.owner
        )
        visible = [
            item for item in source if item.user_id == user_id and item.sequence <= max_sequence
        ]
        return tuple(visible[-limit:])

    async def list_summaries(
        self,
        user_id: str,
        scope_type: ConversationScopeType,
        scope_id: UUID,
        *,
        max_sequence: int,
        limit: int = 2,
    ) -> tuple[ConversationSummaryView, ...]:
        visible = [
            item
            for item in self.summaries
            if item.user_id == user_id and item.to_sequence <= max_sequence
        ]
        return tuple(visible[-limit:])


def _event(
    sequence: int,
    event_type: ConversationEventType,
    content: str,
    *,
    scope: ConversationScopeType = ConversationScopeType.CONVERSATION,
    run_id: UUID | None = None,
    inbox_item_id: UUID | None = None,
    delivery: ConversationDeliveryStatus | None = None,
) -> ConversationEventView:
    scope_id = CONVERSATION_ID if scope is ConversationScopeType.CONVERSATION else OWNER_SCOPE
    return ConversationEventView(
        event_id=uuid4(),
        scope_type=scope,
        scope_id=scope_id,
        user_id="owner",
        sequence=sequence,
        event_type=event_type,
        role=_ROLE[event_type],
        occurred_at=NOW + timedelta(seconds=sequence),
        created_at=NOW + timedelta(seconds=sequence),
        content=content,
        content_ref="",
        content_hash="a" * 64,
        delivery_status=delivery,
        run_id=run_id,
        inbox_item_id=inbox_item_id,
        notification_intent_id=None,
        idempotency_key=f"key-{sequence}",
        metadata={},
    )


def _turn(repository: Repository, sequence: int, label: str, run_id: UUID) -> None:
    repository.conversation.extend(
        (
            _event(
                sequence,
                ConversationEventType.USER_MESSAGE,
                f"用户消息{label}",
                run_id=None,
                inbox_item_id=uuid4(),
            ),
            _event(sequence + 1, ConversationEventType.AGENT_REPLY, f"答复{label}", run_id=run_id),
        )
    )


async def _build(repository: Repository, **kwargs: object) -> TimelineContext:
    current_run_id = kwargs.pop("current_run_id", None)
    current_inbox_item_id = kwargs.pop("current_inbox_item_id", None)
    snapshot = kwargs.pop("snapshot", None)
    assembler = TimelineContextAssembler(repository, **kwargs)  # type: ignore[arg-type]
    return await assembler.build(  # type: ignore[arg-type]
        "owner",
        CONVERSATION_ID,
        current_run_id=current_run_id,
        current_inbox_item_id=current_inbox_item_id,
        snapshot=snapshot,
    )


@pytest.mark.asyncio
async def test_regions_are_ordered_summaries_older_turns_notifications() -> None:
    repository = Repository()
    repository.summaries.append(
        ConversationSummaryView(
            uuid4(),
            "owner",
            ConversationScopeType.CONVERSATION,
            CONVERSATION_ID,
            1,
            2,
            "早期摘要",
            NOW,
            source_hash="b" * 64,
            facts=("已确认事实",),
            decisions=("已作决定",),
        )
    )
    _turn(repository, 1, "一", uuid4())
    _turn(repository, 3, "二", uuid4())
    repository.owner.append(
        _event(
            5,
            ConversationEventType.MAIL_NOTIFICATION,
            "已向用户发送的邮件提醒",
            scope=ConversationScopeType.OWNER_TIMELINE,
            delivery=ConversationDeliveryStatus.DELIVERED,
        )
    )
    _turn(repository, 6, "三", uuid4())

    context = await _build(repository, protected_turns=6)

    kinds = [message.event_type for message in context.messages]
    assert kinds[0] == "CONVERSATION_SUMMARY"
    assert "USER_MESSAGE" in kinds and "AGENT_REPLY" in kinds
    assert kinds[5] == "MAIL_NOTIFICATION"
    assert context.messages[0].role is AgentMessageRole.SYSTEM
    assert context.messages[1].content == "用户消息一"
    assert context.messages[2].content == "答复一"


@pytest.mark.asyncio
async def test_summary_coverage_removes_duplicate_older_events() -> None:
    repository = Repository()
    for index in range(9):
        _turn(repository, index * 2 + 1, str(index), uuid4())
    repository.summaries.append(
        ConversationSummaryView(
            uuid4(),
            "owner",
            ConversationScopeType.CONVERSATION,
            CONVERSATION_ID,
            1,
            2,
            "已压缩第一轮",
            NOW,
            source_hash="b" * 64,
            idempotency_key="summary:dedupe",
        )
    )

    context = await _build(repository)

    contents = [message.content for message in context.messages]
    assert any("已压缩第一轮" in content for content in contents)
    assert not any("用户消息0" in content for content in contents)


@pytest.mark.asyncio
async def test_current_turn_events_are_excluded() -> None:
    repository = Repository()
    current_run = uuid4()
    current_item = uuid4()
    _turn(repository, 1, "一", uuid4())
    repository.conversation.extend(
        (
            _event(
                3,
                ConversationEventType.USER_MESSAGE,
                "当前消息",
                inbox_item_id=current_item,
            ),
            _event(
                4,
                ConversationEventType.TOOL_RESULT,
                "当前工具结果",
                run_id=current_run,
            ),
        )
    )

    context = await _build(
        repository,
        protected_turns=6,
        current_run_id=current_run,
        current_inbox_item_id=current_item,
    )

    contents = [message.content for message in context.messages]
    assert contents == ["用户消息一", "答复一"]


@pytest.mark.asyncio
async def test_protected_zone_covers_only_recent_turns() -> None:
    repository = Repository()
    for index in range(10):
        _turn(repository, index * 2 + 1, f"轮{index}", uuid4())

    context = await _build(repository, protected_turns=6)

    turn_messages = [
        message
        for message in context.messages
        if message.role in {AgentMessageRole.USER, AgentMessageRole.ASSISTANT}
        and not message.content.startswith("[history-event")
    ]
    assert len(turn_messages) == 12
    older = [
        message for message in context.messages if message.content.startswith("[history-event")
    ]
    assert len(older) == 8
    assert turn_messages[0].content == "用户消息轮4"
    assert turn_messages[-1].content == "答复轮9"


@pytest.mark.asyncio
async def test_notification_events_render_as_external_tool_messages() -> None:
    repository = Repository()
    _turn(repository, 1, "一", uuid4())
    repository.owner.extend(
        (
            _event(
                3,
                ConversationEventType.MAIL_NOTIFICATION,
                "已向用户发送的邮件提醒",
                scope=ConversationScopeType.OWNER_TIMELINE,
                delivery=ConversationDeliveryStatus.DELIVERED,
            ),
            _event(
                4,
                ConversationEventType.SYSTEM_RESULT,
                "日程冲突已通知",
                scope=ConversationScopeType.OWNER_TIMELINE,
            ),
        )
    )

    context = await _build(repository)

    notifications = [
        message for message in context.messages if message.role is AgentMessageRole.TOOL
    ]
    assert len(notifications) == 2
    first, second = notifications
    assert first.event_type == "MAIL_NOTIFICATION"
    assert first.delivery_status == "DELIVERED"
    assert first.content.startswith(
        "[external-event MAIL_NOTIFICATION DELIVERED]\n已向用户发送的邮件提醒"
    )
    assert second.event_type == "SYSTEM_RESULT"
    assert second.delivery_status is None
    assert second.content.startswith("[external-event SYSTEM_RESULT]\n日程冲突已通知")


@pytest.mark.asyncio
async def test_empty_timeline_yields_no_messages_with_zero_snapshot() -> None:
    repository = Repository()

    context = await _build(repository)

    assert context.messages == ()
    assert context.snapshot.max_sequence == 0
    assert context.snapshot.revision == 0
    assert context.snapshot.context_hash == snapshot_hash("owner", CONVERSATION_ID, 0)


@pytest.mark.asyncio
async def test_hard_limit_truncates_oldest_turns_and_records_diagnostics() -> None:
    repository = Repository()
    for index in range(8):
        _turn(repository, index * 2 + 1, f"轮{index}{'长' * 3000}", uuid4())

    context = await _build(repository, protected_turns=6, hard_char_limit=10_000)

    truncations = [item for item in context.diagnostics if item.kind == "protected-turns-truncated"]
    assert truncations
    contents = [message.content for message in context.messages]
    assert any("答复轮7" in content for content in contents)
    assert not any("答复轮2" in content for content in contents)


@pytest.mark.asyncio
async def test_duplicate_events_across_scope_reads_are_deduplicated() -> None:
    repository = Repository()
    shared = _event(1, ConversationEventType.USER_MESSAGE, "用户消息一", inbox_item_id=uuid4())
    repository.conversation.append(shared)
    repository.owner.append(shared)

    context = await _build(repository)

    assert [message.content for message in context.messages] == ["用户消息一"]


@pytest.mark.parametrize("turns", [5, 13])
def test_protected_turns_bounds_are_enforced(turns: int) -> None:
    with pytest.raises(ValueError, match="protected turns"):
        TimelineContextAssembler(Repository(), protected_turns=turns)


@pytest.mark.asyncio
async def test_cross_source_events_keep_global_sequence_order() -> None:
    repository = Repository()
    repository.conversation.extend(
        (
            _event(1, ConversationEventType.USER_MESSAGE, "第一条用户消息", inbox_item_id=uuid4()),
            _event(4, ConversationEventType.USER_MESSAGE, "第二条用户消息", inbox_item_id=uuid4()),
            _event(5, ConversationEventType.AGENT_REPLY, "第二条答复", run_id=uuid4()),
        )
    )
    repository.owner.append(
        _event(
            3,
            ConversationEventType.MAIL_NOTIFICATION,
            "邮件提醒",
            scope=ConversationScopeType.OWNER_TIMELINE,
            delivery=ConversationDeliveryStatus.DELIVERED,
        )
    )
    repository.conversation.append(
        _event(2, ConversationEventType.AGENT_REPLY, "第一条答复", run_id=uuid4())
    )

    context = await _build(repository, protected_turns=6)

    assert [message.event_type for message in context.messages] == [
        "USER_MESSAGE",
        "AGENT_REPLY",
        "MAIL_NOTIFICATION",
        "USER_MESSAGE",
        "AGENT_REPLY",
    ]
    assert [message.content for message in context.messages] == [
        "第一条用户消息",
        "第一条答复",
        "[external-event MAIL_NOTIFICATION DELIVERED]\n邮件提醒",
        "第二条用户消息",
        "第二条答复",
    ]


@pytest.mark.asyncio
async def test_daily_digest_precedes_following_conversation_turn() -> None:
    repository = Repository()
    repository.owner.append(
        _event(
            1,
            ConversationEventType.DAILY_DIGEST,
            "日常摘要",
            scope=ConversationScopeType.OWNER_TIMELINE,
            delivery=ConversationDeliveryStatus.DELIVERED,
        )
    )
    _turn(repository, 2, "摘要后的对话", uuid4())

    context = await _build(repository)

    assert [message.event_type for message in context.messages] == [
        "DAILY_DIGEST",
        "USER_MESSAGE",
        "AGENT_REPLY",
    ]


@pytest.mark.asyncio
async def test_owner_timeline_isolated_by_user() -> None:
    repository = Repository()
    current = _event(
        1,
        ConversationEventType.DAILY_DIGEST,
        "当前用户摘要",
        scope=ConversationScopeType.OWNER_TIMELINE,
        delivery=ConversationDeliveryStatus.DELIVERED,
    )
    other = _event(
        2,
        ConversationEventType.DAILY_DIGEST,
        "其他用户摘要",
        scope=ConversationScopeType.OWNER_TIMELINE,
        delivery=ConversationDeliveryStatus.DELIVERED,
    )
    repository.owner.extend((current, _with_user(other, "other-owner")))

    context = await _build(repository)

    assert [message.content for message in context.messages] == [
        "[external-event DAILY_DIGEST DELIVERED]\n当前用户摘要"
    ]


def _with_user(event: ConversationEventView, user_id: str) -> ConversationEventView:
    return ConversationEventView(
        event.event_id,
        event.scope_type,
        event.scope_id,
        user_id,
        event.sequence,
        event.event_type,
        event.role,
        event.occurred_at,
        event.created_at,
        event.content,
        event.content_ref,
        event.content_hash,
        event.delivery_status,
        event.run_id,
        event.inbox_item_id,
        event.notification_intent_id,
        event.idempotency_key,
        event.metadata,
    )


@pytest.mark.asyncio
async def test_summary_write_rejects_duplicate_source_sequence() -> None:
    first = _event(1, ConversationEventType.USER_MESSAGE, "一", inbox_item_id=uuid4())
    duplicate = _event(1, ConversationEventType.AGENT_REPLY, "二", run_id=uuid4())
    summary = ConversationSummaryView(
        uuid4(),
        "owner",
        ConversationScopeType.CONVERSATION,
        CONVERSATION_ID,
        1,
        1,
        "摘要",
        NOW,
        source_hash="a" * 64,
        idempotency_key="summary-1",
    )
    with pytest.raises(ValueError, match="strictly increasing"):
        ConversationSummaryWrite(summary, (first, duplicate))


@pytest.mark.asyncio
async def test_summary_write_uses_immutable_source_hash() -> None:
    first = _event(1, ConversationEventType.USER_MESSAGE, "一", inbox_item_id=uuid4())
    second = _event(2, ConversationEventType.AGENT_REPLY, "二", run_id=uuid4())
    source = (first, second)
    summary = ConversationSummaryView(
        uuid4(),
        "owner",
        ConversationScopeType.CONVERSATION,
        CONVERSATION_ID,
        1,
        2,
        "摘要",
        NOW,
        source_hash=summary_source_hash(source),
        idempotency_key="summary-2",
    )
    request = ConversationSummaryWrite(summary, source)
    assert request.source_events == source


@pytest.mark.asyncio
async def test_timeline_budget_records_compression_preparation_without_content() -> None:
    repository = Repository()
    _turn(repository, 1, "A" * 60, uuid4())

    context = await _build(
        repository,
        budget=ContextBudgetPolicy(max_context_tokens=60, safety_margin_tokens=2),
    )

    diagnostics = [item for item in context.diagnostics if item.kind == "compression-preparation"]
    assert diagnostics
    assert "ratio=" in diagnostics[0].detail
    assert "AAAA" not in diagnostics[0].detail


@pytest.mark.asyncio
async def test_pinned_snapshot_excludes_events_arriving_during_execution() -> None:
    repository = Repository()
    _turn(repository, 1, "快照前", uuid4())
    snapshot = await repository.create_snapshot("owner", CONVERSATION_ID)
    repository.conversation.extend(
        (
            _event(3, ConversationEventType.USER_MESSAGE, "快照后消息", inbox_item_id=uuid4()),
            _event(4, ConversationEventType.AGENT_REPLY, "快照后答复", run_id=uuid4()),
        )
    )

    context = await _build(repository, snapshot=snapshot)

    assert [message.content for message in context.messages] == ["用户消息快照前", "答复快照前"]
    assert context.snapshot == snapshot


@pytest.mark.asyncio
async def test_older_events_beyond_limit_record_diagnostics() -> None:
    repository = Repository()
    for index in range(10):
        _turn(repository, index * 2 + 1, f"轮{index}", uuid4())

    context = await _build(repository, protected_turns=6, older_event_limit=4)

    bounded = [item for item in context.diagnostics if item.kind == "older-events-bounded"]
    assert bounded and bounded[0].detail == "dropped_events=4"
    older = [
        message for message in context.messages if message.content.startswith("[history-event")
    ]
    assert len(older) == 4


@pytest.mark.asyncio
async def test_selection_diagnostics_are_bounded_and_do_not_include_content() -> None:
    repository = Repository()
    _turn(repository, 1, "敏感 QQ 正文", uuid4())
    repository.owner.append(
        _event(
            3,
            ConversationEventType.MAIL_NOTIFICATION,
            "敏感邮件正文",
            scope=ConversationScopeType.OWNER_TIMELINE,
            delivery=ConversationDeliveryStatus.DELIVERED,
        )
    )

    context = await _build(repository)

    diagnostics = [item for item in context.diagnostics if item.kind == "timeline-selection"]
    assert len(diagnostics) == 1
    detail = diagnostics[0].detail
    assert "sequence_range=1-3" in detail
    assert "context_hash=" in detail
    assert "敏感" not in detail
    assert "scope=" in detail
