from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from qq_time_agent.modules.inbox.domain.models import InboxItem, InboxStatus, MailEnvelope


def _envelope() -> MailEnvelope:
    now = datetime(2026, 8, 13, tzinfo=UTC)
    return MailEnvelope(
        uuid4(),
        "owner",
        "message-1",
        "thread-1",
        "sender@example.test",
        "Sender",
        now,
        now + timedelta(seconds=1),
        "a" * 64,
    )


def test_mail_envelope_is_timezone_aware_and_required() -> None:
    envelope = _envelope()
    assert envelope.external_id == "message-1"
    with pytest.raises(ValueError, match="required"):
        MailEnvelope(
            envelope.connection_id,
            " ",
            envelope.external_id,
            None,
            envelope.sender_id,
            None,
            envelope.occurred_at,
            envelope.received_at,
            envelope.content_hash,
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        MailEnvelope(
            envelope.connection_id,
            envelope.user_id,
            envelope.external_id,
            None,
            envelope.sender_id,
            None,
            datetime(2026, 8, 13),
            envelope.received_at,
            envelope.content_hash,
        )


def test_inbox_state_machine_retry_normalize_complete() -> None:
    item = InboxItem.receive(_envelope(), uuid4())
    item.mark_failed("TransientProvider", True)
    assert item.status is InboxStatus.FAILED_RETRYABLE
    assert item.retry_count == 1
    item.retry()
    item.mark_normalized()
    item.mark_completed()
    assert item.status.value == "COMPLETED"
    assert item.source_type.value == "MICROSOFT_MAIL"
    assert item.trust_level.value == "T2"
    with pytest.raises(ValueError, match="terminal"):
        item.mark_failed("PermanentProvider", False)


def test_inbox_rejects_invalid_transitions_and_empty_failure() -> None:
    item = InboxItem.receive(_envelope(), uuid4())
    with pytest.raises(ValueError, match="invalid Inbox transition"):
        item.mark_completed()
    with pytest.raises(ValueError, match="failure_class"):
        item.mark_failed(" ", True)
    item.mark_failed("PermanentProvider", False)
    assert item.status is InboxStatus.FAILED_FINAL


@pytest.mark.parametrize(
    "method,target",
    [
        ("mark_understood", InboxStatus.UNDERSTOOD),
        ("mark_needs_review", InboxStatus.NEEDS_REVIEW),
        ("mark_ignored", InboxStatus.IGNORED),
    ],
)
def test_normalized_item_has_explicit_understanding_dispositions(
    method: str, target: InboxStatus
) -> None:
    item = InboxItem.receive(_envelope(), uuid4())
    item.mark_normalized()
    getattr(item, method)()
    assert item.status is target
