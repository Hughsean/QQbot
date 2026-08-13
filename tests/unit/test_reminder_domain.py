from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from qq_time_agent.modules.reminders.domain.models import Reminder, ReminderStatus


def _reminder() -> Reminder:
    return Reminder.create(uuid4(), 1, datetime(2026, 8, 20, tzinfo=UTC), "reminder:test")


def test_reminder_lease_expiry_retry_and_exactly_once_terminal_state() -> None:
    now = datetime(2026, 8, 20, tzinfo=UTC)
    reminder = _reminder()
    reminder.lease("worker-a", now, timedelta(minutes=1))
    with pytest.raises(ValueError, match="active"):
        reminder.lease("worker-b", now + timedelta(seconds=30), timedelta(minutes=1))
    reminder.lease("worker-b", now + timedelta(minutes=2), timedelta(minutes=1))
    reminder.mark_failed("worker-b", "RateLimit", now + timedelta(minutes=3))
    assert reminder.status is ReminderStatus.RETRY_WAIT
    reminder.lease("worker-c", now + timedelta(minutes=3), timedelta(minutes=1))
    reminder.mark_sent("worker-c", "delivery-1")
    assert reminder.status.value == "SENT"
    with pytest.raises(ValueError, match="lease"):
        reminder.mark_sent("worker-c", "delivery-2")


def test_reminder_cancel_snooze_and_validation() -> None:
    now = datetime(2026, 8, 20, tzinfo=UTC)
    reminder = _reminder()
    reminder.cancel()
    assert reminder.status is ReminderStatus.CANCELLED
    sent = _reminder()
    sent.lease("worker", now, timedelta(minutes=1))
    sent.mark_sent("worker", "delivery")
    sent.snooze(timedelta(minutes=10), now)
    assert sent.status is ReminderStatus.SCHEDULED
    assert sent.due_at == now + timedelta(minutes=10)
    assert sent.occurrence == 2
    with pytest.raises(ValueError, match="sent"):
        reminder.snooze(timedelta(minutes=10), now)


def test_reminder_rejects_invalid_creation_leases_delivery_and_dead_letter() -> None:
    now = datetime(2026, 8, 20, tzinfo=UTC)
    with pytest.raises(ValueError, match="required"):
        Reminder.create(uuid4(), 0, now, "")
    with pytest.raises(ValueError, match="timezone-aware"):
        Reminder.create(uuid4(), 1, datetime(2026, 8, 20), "key")
    reminder = _reminder()
    with pytest.raises(ValueError, match="positive"):
        reminder.lease("", now, timedelta(0))
    reminder.lease("worker", now, timedelta(minutes=1))
    with pytest.raises(ValueError, match="delivery"):
        reminder.mark_sent("worker", "")
    with pytest.raises(ValueError, match="failure"):
        reminder.mark_failed("worker", "", None)
    reminder.mark_failed("worker", "PermanentProvider", None)
    assert reminder.status is ReminderStatus.DEAD_LETTER
    with pytest.raises(ValueError, match="terminal"):
        reminder.cancel()
