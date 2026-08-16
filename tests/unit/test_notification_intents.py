from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta

import pytest

from qq_time_agent.modules.identity.contracts import UserPreferencesView
from qq_time_agent.modules.notifications.application.intent_delivery import (
    NotificationIntentDeliveryService,
)
from qq_time_agent.modules.notifications.contracts import (
    NotificationPreSendPermanentError,
    NotificationPreSendTransientError,
)
from qq_time_agent.modules.notifications.domain.models import (
    NotificationIntent,
    NotificationIntentDraft,
    NotificationIntentState,
    NotificationKind,
)
from qq_time_agent.modules.notifications.domain.policy import next_allowed_at

NOW = datetime(2026, 8, 15, 14, tzinfo=UTC)


def _draft() -> NotificationIntentDraft:
    return NotificationIntentDraft(
        "owner",
        NotificationKind.DAILY_DIGEST,
        "daily-digest:owner",
        "daily-digest:owner:2026-08-15:v1",
        "v1",
        "digest",
        NOW,
    )


def _preferences(**changes: object) -> UserPreferencesView:
    values: dict[str, object] = {
        "user_id": "owner",
        "timezone": "Asia/Shanghai",
        "work_start": time(9),
        "work_end": time(18),
        "lunch_start": time(12),
        "lunch_end": time(13),
        "working_weekdays": (0, 1, 2, 3, 4),
        "default_event_minutes": 60,
        "default_task_minutes": 30,
    }
    values.update(changes)
    return UserPreferencesView(**values)  # type: ignore[arg-type]


def _state(value: NotificationIntent) -> NotificationIntentState:
    return value.state


def test_notification_intent_transitions_are_versioned_and_terminal() -> None:
    value = NotificationIntent.create(_draft(), NOW)
    value.lease("qq-1", NOW + timedelta(seconds=30), NOW)
    assert _state(value) is NotificationIntentState.LEASED and value.version == 2
    value.mark_sent("delivery-1", NOW + timedelta(seconds=1))
    assert _state(value) is NotificationIntentState.SENT and value.version == 3
    with pytest.raises(ValueError):
        value.cancel(NOW)


def test_quiet_hours_defer_overnight_and_allow_daytime() -> None:
    preferences = _preferences()
    quiet = datetime(2026, 8, 15, 15, tzinfo=UTC)  # 23:00 Asia/Shanghai
    assert next_allowed_at(quiet, preferences) == datetime(2026, 8, 15, 23, tzinfo=UTC)
    daytime = datetime(2026, 8, 15, 4, tzinfo=UTC)
    assert next_allowed_at(daytime, preferences) == daytime


def test_quiet_hours_are_deterministic_across_dst_transitions() -> None:
    preferences = _preferences(
        timezone="America/New_York",
        quiet_start=time(0),
        quiet_end=time(2, 30),
    )
    spring = datetime(2026, 3, 8, 6, tzinfo=UTC)  # 01:00 before spring gap
    assert next_allowed_at(spring, preferences) == datetime(2026, 3, 8, 7, 30, tzinfo=UTC)

    fall_preferences = _preferences(
        timezone="America/New_York",
        quiet_start=time(0),
        quiet_end=time(1, 30),
    )
    fall = datetime(2026, 11, 1, 4, 30, tzinfo=UTC)  # 00:30 before repeated hour
    assert next_allowed_at(fall, fall_preferences) == datetime(2026, 11, 1, 5, 30, tzinfo=UTC)
    repeated = datetime(2026, 11, 1, 6, 15, tzinfo=UTC)  # second 01:15
    assert next_allowed_at(repeated, fall_preferences) == datetime(2026, 11, 1, 6, 30, tzinfo=UTC)


@dataclass
class IntentRepository:
    value: NotificationIntent
    saved: list[NotificationIntentState] = field(default_factory=list)

    async def add_or_get(self, draft: NotificationIntentDraft, now: datetime) -> NotificationIntent:
        return self.value

    async def has_open(self, subject_key: str) -> bool:
        return False

    async def has_recent_sent(self, subject_key: str, since: datetime) -> bool:
        return False

    async def recover_expired(self, now: datetime, limit: int) -> int:
        return 0

    async def lease_due(
        self, now: datetime, owner: str, duration: timedelta, limit: int
    ) -> tuple[NotificationIntent, ...]:
        self.value.lease(owner, now + duration, now)
        return (self.value,)

    async def save(self, intent: NotificationIntent, expected_version: int) -> None:
        assert intent.version == expected_version + 1
        self.saved.append(intent.state)


@dataclass
class Eligibility:
    value: datetime | None

    async def eligible_at(self, intent: NotificationIntent, now: datetime) -> datetime | None:
        return self.value


@dataclass
class FailingEligibility:
    async def eligible_at(self, intent: NotificationIntent, now: datetime) -> datetime | None:
        raise ConnectionError("agenda query unavailable")


@dataclass
class Sender:
    values: list[str] = field(default_factory=list)

    async def send_active(self, content: str) -> str:
        self.values.append(content)
        return "delivery-1"


@pytest.mark.asyncio
async def test_delivery_leases_revalidates_and_sends_once() -> None:
    repository = IntentRepository(NotificationIntent.create(_draft(), NOW))
    sender = Sender()
    service = NotificationIntentDeliveryService(repository, Eligibility(NOW), sender, "qq-1")
    assert await service.run_once(NOW) == 1
    assert sender.values == ["digest"]
    assert repository.saved == [NotificationIntentState.SENT]


@pytest.mark.asyncio
async def test_delivery_cancels_stale_source_without_sending() -> None:
    repository = IntentRepository(NotificationIntent.create(_draft(), NOW))
    sender = Sender()
    service = NotificationIntentDeliveryService(repository, Eligibility(None), sender, "qq-1")
    assert await service.run_once(NOW) == 0
    assert sender.values == []
    assert repository.saved == [NotificationIntentState.CANCELLED]


@pytest.mark.asyncio
async def test_delivery_rechecks_quiet_hours_and_defers_lease() -> None:
    repository = IntentRepository(NotificationIntent.create(_draft(), NOW))
    sender = Sender()
    service = NotificationIntentDeliveryService(
        repository, Eligibility(NOW + timedelta(hours=1)), sender, "qq-1"
    )
    assert await service.run_once(NOW) == 0
    assert sender.values == []
    assert repository.saved == [NotificationIntentState.PENDING]
    assert repository.value.draft.available_at == NOW + timedelta(hours=1)


@pytest.mark.asyncio
async def test_eligibility_failure_retries_without_contacting_sender() -> None:
    repository = IntentRepository(NotificationIntent.create(_draft(), NOW))
    sender = Sender()
    service = NotificationIntentDeliveryService(repository, FailingEligibility(), sender, "qq-1")
    assert await service.run_once(NOW) == 0
    assert sender.values == []
    assert repository.saved == [NotificationIntentState.PENDING]


@dataclass
class FailingSender:
    permanent: bool = False

    async def send_active(self, content: str) -> str:
        if self.permanent:
            raise NotificationPreSendPermanentError("rejected before request")
        raise NotificationPreSendTransientError("disconnected before request")


@pytest.mark.asyncio
async def test_pre_send_failure_retries_then_dead_letters() -> None:
    value = NotificationIntent.create(_draft(), NOW)
    repository = IntentRepository(value)
    transient = NotificationIntentDeliveryService(
        repository, Eligibility(NOW), FailingSender(), "qq-1"
    )
    assert await transient.run_once(NOW) == 0
    assert repository.saved == [NotificationIntentState.PENDING]

    value.attempt_count = 2
    value.state = NotificationIntentState.PENDING
    permanent = NotificationIntentDeliveryService(
        repository, Eligibility(NOW), FailingSender(permanent=True), "qq-1"
    )
    assert await permanent.run_once(NOW) == 0
    assert repository.saved[-1] is NotificationIntentState.DEAD_LETTER
