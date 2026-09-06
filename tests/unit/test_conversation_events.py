"""Unified conversation timeline event contract validation."""

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import uuid4

import pytest

from qq_time_agent.modules.agent.contracts import (
    ConversationDeliveryStatus,
    ConversationEvent,
    ConversationEventRole,
    ConversationEventType,
    ConversationScopeType,
    NotificationEventRequest,
    bounded_event_content,
    is_notification_event,
    owner_timeline_scope_id,
)

NOW = datetime(2026, 8, 27, 10, tzinfo=UTC)
LATER = NOW + timedelta(minutes=5)


def _user_message(**overrides: object) -> ConversationEvent:
    values: dict[str, object] = {
        "scope_type": ConversationScopeType.CONVERSATION,
        "scope_id": uuid4(),
        "user_id": "owner",
        "event_type": ConversationEventType.USER_MESSAGE,
        "occurred_at": NOW,
        "content": "把会议改到明天",
        "idempotency_key": "user-message:00000000-0000-0000-0000-000000000001",
        "inbox_item_id": uuid4(),
        "content_ref": "inbox:00000000-0000-0000-0000-000000000001",
    }
    values.update(overrides)
    return ConversationEvent(**values)  # type: ignore[arg-type]


def _agent_reply(**overrides: object) -> ConversationEvent:
    values: dict[str, object] = {
        "scope_type": ConversationScopeType.CONVERSATION,
        "scope_id": uuid4(),
        "user_id": "owner",
        "event_type": ConversationEventType.AGENT_REPLY,
        "occurred_at": LATER,
        "content": "已把会议改到明天 10:00。",
        "idempotency_key": "agent-reply:00000000-0000-0000-0000-000000000002",
        "run_id": uuid4(),
        "content_ref": "agent-run:00000000-0000-0000-0000-000000000002",
    }
    values.update(overrides)
    return ConversationEvent(**values)  # type: ignore[arg-type]


def _mail_notification(**overrides: object) -> ConversationEvent:
    values: dict[str, object] = {
        "scope_type": ConversationScopeType.OWNER_TIMELINE,
        "scope_id": owner_timeline_scope_id("owner"),
        "user_id": "owner",
        "event_type": ConversationEventType.MAIL_NOTIFICATION,
        "occurred_at": LATER,
        "content": "[邮件处理\N{FULLWIDTH VERTICAL LINE}Outlook]\n主题\N{FULLWIDTH COLON}项目评审",
        "idempotency_key": "notification:00000000-0000-0000-0000-000000000003",
        "notification_intent_id": uuid4(),
        "delivery_status": ConversationDeliveryStatus.DELIVERED,
    }
    values.update(overrides)
    return ConversationEvent(**values)  # type: ignore[arg-type]


def test_event_derives_role_and_content_hash() -> None:
    event = _user_message()
    assert event.role is ConversationEventRole.USER
    assert event.content_hash == sha256("把会议改到明天".encode()).hexdigest()
    reply = _agent_reply()
    assert reply.role is ConversationEventRole.AGENT
    system = _mail_notification()
    assert system.role is ConversationEventRole.SYSTEM


@pytest.mark.parametrize("field", ["occurred_at", "created_at"])
def test_event_rejects_naive_datetime(field: str) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        _user_message(**{field: datetime(2026, 8, 27, 10)})


def test_event_rejects_blank_user_idempotency_and_content() -> None:
    with pytest.raises(ValueError, match="user is required"):
        _user_message(user_id="  ")
    with pytest.raises(ValueError, match="idempotency key is required"):
        _user_message(idempotency_key="")
    with pytest.raises(ValueError, match="content is required"):
        _user_message(content="   ")


def test_event_rejects_oversized_content_and_reference() -> None:
    with pytest.raises(ValueError, match="bounded"):
        _user_message(content="长" * 12_001)
    with pytest.raises(ValueError, match="content reference"):
        _user_message(content_ref="x" * 161)
    with pytest.raises(ValueError, match="idempotency key is required"):
        _user_message(idempotency_key="k" * 256)


def test_event_rejects_oversized_or_blank_metadata() -> None:
    with pytest.raises(ValueError, match="metadata is too large"):
        _user_message(metadata={f"key{index}": 1 for index in range(33)})
    with pytest.raises(ValueError, match="metadata keys are required"):
        _user_message(metadata={"": 1})


def test_user_message_requires_inbox_item() -> None:
    with pytest.raises(ValueError, match="requires its inbox item"):
        _user_message(inbox_item_id=None)


@pytest.mark.parametrize(
    "event_type",
    [
        ConversationEventType.AGENT_REPLY,
        ConversationEventType.TOOL_CALL,
        ConversationEventType.TOOL_RESULT,
    ],
)
def test_run_events_require_run_id(event_type: ConversationEventType) -> None:
    with pytest.raises(ValueError, match="requires its AgentRun"):
        _agent_reply(event_type=event_type, run_id=None)


def test_notification_event_requires_intent_and_delivery_status() -> None:
    with pytest.raises(ValueError, match="requires its notification intent"):
        _mail_notification(notification_intent_id=None)
    with pytest.raises(ValueError, match="requires a delivery status"):
        _mail_notification(delivery_status=None)


def test_non_notification_event_cannot_carry_delivery_status() -> None:
    with pytest.raises(ValueError, match="cannot carry a delivery status"):
        _agent_reply(delivery_status=ConversationDeliveryStatus.DELIVERED)


def test_system_result_event_may_carry_notification_delivery() -> None:
    intent_id = uuid4()
    event = ConversationEvent(
        scope_type=ConversationScopeType.OWNER_TIMELINE,
        scope_id=owner_timeline_scope_id("owner"),
        user_id="owner",
        event_type=ConversationEventType.SYSTEM_RESULT,
        occurred_at=LATER,
        content="[日程冲突]\n两条日程重叠",
        idempotency_key=f"notification:{intent_id}",
        notification_intent_id=intent_id,
        delivery_status=ConversationDeliveryStatus.DELIVERED,
        content_ref=f"notification-intent:{intent_id}",
    )
    assert event.role is ConversationEventRole.SYSTEM


def test_system_result_event_with_status_requires_intent() -> None:
    with pytest.raises(ValueError, match="system notification event requires its notification"):
        ConversationEvent(
            scope_type=ConversationScopeType.OWNER_TIMELINE,
            scope_id=owner_timeline_scope_id("owner"),
            user_id="owner",
            event_type=ConversationEventType.SYSTEM_RESULT,
            occurred_at=LATER,
            content="日历变更已确认",
            idempotency_key="system-result:1",
            delivery_status=ConversationDeliveryStatus.DELIVERED,
        )


def test_event_scope_must_match_its_type() -> None:
    with pytest.raises(ValueError, match="requires conversation scope"):
        _user_message(scope_type=ConversationScopeType.OWNER_TIMELINE)
    with pytest.raises(ValueError, match="requires owner_timeline scope"):
        _mail_notification(scope_type=ConversationScopeType.CONVERSATION)
    with pytest.raises(ValueError, match="requires owner_timeline scope"):
        _agent_reply(event_type=ConversationEventType.SYSTEM_RESULT)


def test_owner_timeline_scope_id_is_stable_and_user_scoped() -> None:
    first = owner_timeline_scope_id("owner")
    assert first == owner_timeline_scope_id("owner")
    assert first != owner_timeline_scope_id("other-owner")


def test_notification_event_request_builds_owner_timeline_event() -> None:
    intent_id = uuid4()
    request = NotificationEventRequest(
        "owner",
        ConversationEventType.MAIL_DIGEST,
        intent_id,
        "2026-08-27 邮件摘要\n08:30 周报: 已整理",
        ConversationDeliveryStatus.DELIVERED,
        LATER,
        f"notification:{intent_id}",
    )
    event = request.to_event()
    assert event.scope_type is ConversationScopeType.OWNER_TIMELINE
    assert event.scope_id == owner_timeline_scope_id("owner")
    assert event.notification_intent_id == intent_id
    assert event.delivery_status is ConversationDeliveryStatus.DELIVERED
    assert event.content_ref == f"notification-intent:{intent_id}"
    assert event.role is ConversationEventRole.SYSTEM


def test_notification_event_request_rejects_non_notification_type() -> None:
    with pytest.raises(ValueError, match="notification event type is required"):
        NotificationEventRequest(
            "owner",
            ConversationEventType.USER_MESSAGE,
            uuid4(),
            "内容",
            ConversationDeliveryStatus.DELIVERED,
            LATER,
            "notification:1",
        )


def test_notification_event_request_accepts_system_notification_kind() -> None:
    intent_id = uuid4()
    request = NotificationEventRequest(
        "owner",
        ConversationEventType.SYSTEM_RESULT,
        intent_id,
        "[系统通知]\n邮箱连接需要重新授权",
        ConversationDeliveryStatus.FAILED,
        LATER,
        f"notification:{intent_id}",
    )
    event = request.to_event()
    assert event.event_type is ConversationEventType.SYSTEM_RESULT
    assert event.delivery_status is ConversationDeliveryStatus.FAILED


def test_bounded_event_content_truncates_deterministically() -> None:
    short = bounded_event_content("短内容")
    assert short == "短内容"
    long = "长" * 12_500
    bounded = bounded_event_content(long)
    assert len(bounded) == 12_000
    assert bounded.endswith("…[event-truncated]")
    assert bounded_event_content(bounded) == bounded


def test_notification_event_request_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        NotificationEventRequest(
            "owner",
            ConversationEventType.MAIL_NOTIFICATION,
            uuid4(),
            "内容",
            ConversationDeliveryStatus.FAILED,
            datetime(2026, 8, 27, 10),
            "notification:2",
        )


def test_notification_kinds_are_classified() -> None:
    assert is_notification_event(ConversationEventType.MAIL_NOTIFICATION)
    assert is_notification_event(ConversationEventType.MAIL_DIGEST)
    assert is_notification_event(ConversationEventType.DAILY_DIGEST)
    assert not is_notification_event(ConversationEventType.USER_MESSAGE)
    assert not is_notification_event(ConversationEventType.AGENT_REPLY)
    assert not is_notification_event(ConversationEventType.TOOL_RESULT)
    assert not is_notification_event(ConversationEventType.SYSTEM_RESULT)
