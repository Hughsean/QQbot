"""Notification delivery mirroring into the owner timeline."""

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from qq_time_agent.modules.agent.contracts import (
    ConversationDeliveryStatus,
    ConversationEventType,
    NotificationEventRequest,
)
from qq_time_agent.modules.notifications.application.intent_delivery import (
    NotificationIntentDeliveryService,
)
from qq_time_agent.modules.notifications.contracts import (
    NotificationPreSendPermanentError,
    NotificationPreSendTransientError,
)
from qq_time_agent.modules.notifications.contracts.actions import NotificationMessage
from qq_time_agent.modules.notifications.domain.models import (
    NotificationIntent,
    NotificationIntentDraft,
    NotificationIntentState,
    NotificationKind,
)

NOW = datetime(2026, 8, 15, 14, tzinfo=UTC)


def _draft(kind: NotificationKind, content: str = "digest") -> NotificationIntentDraft:
    return NotificationIntentDraft(
        "owner",
        kind,
        f"{kind.value.lower()}:owner",
        f"{kind.value.lower()}:owner:2026-08-15:v1",
        "v1",
        content,
        NOW,
    )


@dataclass
class Repository:
    intents: list[NotificationIntent]
    saved: list[NotificationIntentState] = field(default_factory=list)
    settled: list[NotificationIntent] = field(default_factory=list)

    async def add_or_get(self, draft: NotificationIntentDraft, now: datetime) -> NotificationIntent:
        del now
        return NotificationIntent.create(draft, NOW)

    async def recover_expired(self, now: datetime, limit: int) -> int:
        del now, limit
        return 0

    async def lease_due(
        self, now: datetime, owner: str, duration: timedelta, limit: int
    ) -> tuple[NotificationIntent, ...]:
        del now, duration, limit
        leased: list[NotificationIntent] = []
        for value in self.intents:
            if value.state is NotificationIntentState.PENDING:
                value.lease(owner, NOW + timedelta(seconds=30), NOW)
                leased.append(value)
        return tuple(leased)

    async def save(self, intent: NotificationIntent, expected_version: int) -> None:
        assert intent.version == expected_version + 1
        self.saved.append(intent.state)
        self.settled = [
            value if value.intent_id != intent.intent_id else intent for value in self.settled
        ]
        if intent.state in {NotificationIntentState.SENT, NotificationIntentState.DEAD_LETTER}:
            self.settled.append(intent)

    async def has_open(self, subject_key: str) -> bool:
        del subject_key
        return False

    async def has_recent_sent(self, subject_key: str, since: datetime) -> bool:
        del subject_key, since
        return False

    async def list_immediate_mail_run_ids(
        self, user_id: str, run_ids: tuple[UUID, ...]
    ) -> frozenset[UUID]:
        del user_id, run_ids
        return frozenset()

    async def list_recently_settled(
        self, since: datetime, limit: int
    ) -> tuple[NotificationIntent, ...]:
        del since, limit
        return tuple(self.settled)


@dataclass
class Eligibility:
    async def eligible_at(self, intent: NotificationIntent, now: datetime) -> datetime | None:
        del intent
        return now


@dataclass
class Sender:
    failure: Exception | None = None

    async def send_active(self, content: str) -> str:
        if self.failure is not None:
            raise self.failure
        return "delivery-1"

    async def send_message(self, message: NotificationMessage) -> str:
        del message
        return "delivery-1"


@dataclass
class Timeline:
    requests: list[NotificationEventRequest] = field(default_factory=list)
    failure: Exception | None = None

    async def record_notification_event(self, request: NotificationEventRequest) -> None:
        if self.failure is not None:
            raise self.failure
        existing = next(
            (
                item
                for item in self.requests
                if item.idempotency_key == request.idempotency_key
            ),
            None,
        )
        if existing is None:
            self.requests.append(request)


def _service(
    repository: Repository, timeline: Timeline, sender: Sender | None = None
) -> NotificationIntentDeliveryService:
    return NotificationIntentDeliveryService(
        repository,
        Eligibility(),
        sender or Sender(),
        "qq-1",
        timeline=timeline,
    )


@pytest.mark.asyncio
async def test_sent_notification_mirrors_delivered_snapshot_into_timeline() -> None:
    intent = NotificationIntent.create(_draft(NotificationKind.OUTLOOK_MAIL_RESULT), NOW)
    repository = Repository([intent])
    timeline = Timeline()

    assert await _service(repository, timeline).run_once(NOW) == 1

    assert len(timeline.requests) == 1
    request = timeline.requests[0]
    assert request.event_type is ConversationEventType.MAIL_NOTIFICATION
    assert request.delivery_status is ConversationDeliveryStatus.DELIVERED
    assert request.idempotency_key == f"notification:{intent.intent_id}"
    assert request.occurred_at == intent.sent_at
    assert request.content.startswith("[邮件处理\N{FULLWIDTH VERTICAL LINE}Outlook]\n")
    assert "digest" in request.content


@pytest.mark.asyncio
async def test_repeated_cycles_keep_a_single_idempotent_timeline_key() -> None:
    intent = NotificationIntent.create(_draft(NotificationKind.DAILY_DIGEST), NOW)
    repository = Repository([intent])
    timeline = Timeline()
    service = _service(repository, timeline)

    await service.run_once(NOW)
    await service.run_once(NOW + timedelta(seconds=5))
    await service.run_once(NOW + timedelta(seconds=10))

    assert len(timeline.requests) == 1
    assert {request.idempotency_key for request in timeline.requests} == {
        f"notification:{intent.intent_id}"
    }
    assert all(
        request.event_type is ConversationEventType.DAILY_DIGEST for request in timeline.requests
    )


@pytest.mark.asyncio
async def test_settled_content_snapshot_is_unchanged_when_draft_mutates() -> None:
    intent = NotificationIntent.create(_draft(NotificationKind.MAIL_DIGEST, "original"), NOW)
    repository = Repository([intent])
    timeline = Timeline()
    service = _service(repository, timeline)

    await service.run_once(NOW)
    original = timeline.requests[0].content
    intent.draft = replace(intent.draft, content="mutated")

    await service.run_once(NOW + timedelta(seconds=5))

    assert timeline.requests[0].content == original
    assert len(timeline.requests) == 1


@pytest.mark.asyncio
async def test_failed_event_never_becomes_delivered_on_retry_reconciliation() -> None:
    intent = NotificationIntent.create(_draft(NotificationKind.QQ_MAIL_RESULT), NOW)
    intent.attempt_count = 2
    repository = Repository([intent])
    timeline = Timeline()
    sender = Sender(failure=NotificationPreSendPermanentError("rejected"))
    service = _service(repository, timeline, sender)

    await service.run_once(NOW)
    intent.state = NotificationIntentState.SENT  # simulate an inconsistent external mutation
    intent.sent_at = NOW + timedelta(seconds=1)
    await _service(repository, timeline).run_once(NOW + timedelta(seconds=2))

    assert timeline.requests[0].delivery_status is ConversationDeliveryStatus.FAILED


@pytest.mark.asyncio
async def test_system_result_is_used_for_calendar_and_reauth_notifications() -> None:
    for kind in (NotificationKind.AGENDA_CONFLICT, NotificationKind.CONNECTION_REAUTH):
        intent = NotificationIntent.create(_draft(kind), NOW)
        repository = Repository([intent])
        timeline = Timeline()

        await _service(repository, timeline).run_once(NOW)

        assert timeline.requests[0].event_type is ConversationEventType.SYSTEM_RESULT


@pytest.mark.asyncio
async def test_transient_failure_then_retry_success_records_delivered() -> None:
    intent = NotificationIntent.create(_draft(NotificationKind.AGENDA_CONFLICT), NOW)
    repository = Repository([intent])
    timeline = Timeline()
    sender = Sender(failure=NotificationPreSendTransientError("disconnected"))
    service = _service(repository, timeline, sender)

    await service.run_once(NOW)
    assert repository.saved == [NotificationIntentState.PENDING]
    assert timeline.requests == []

    intent.attempt_count = 2
    intent.state = NotificationIntentState.PENDING
    delivered = await _service(repository, timeline, Sender(failure=None)).run_once(NOW)
    assert delivered == 1

    assert repository.saved[-1] is NotificationIntentState.SENT
    assert len(timeline.requests) == 1
    assert timeline.requests[0].delivery_status is ConversationDeliveryStatus.DELIVERED
    assert timeline.requests[0].event_type is ConversationEventType.SYSTEM_RESULT


@pytest.mark.asyncio
async def test_permanent_failure_records_dead_letter_as_failed_event() -> None:
    intent = NotificationIntent.create(_draft(NotificationKind.QQ_MAIL_RESULT), NOW)
    intent.attempt_count = 2
    repository = Repository([intent])
    timeline = Timeline()
    sender = Sender(failure=NotificationPreSendPermanentError("rejected"))

    assert await _service(repository, timeline, sender).run_once(NOW) == 0
    assert repository.saved == [NotificationIntentState.DEAD_LETTER]
    assert len(timeline.requests) == 1
    request = timeline.requests[0]
    assert request.delivery_status is ConversationDeliveryStatus.FAILED
    assert request.event_type is ConversationEventType.MAIL_NOTIFICATION
    assert request.occurred_at == intent.updated_at

    await _service(repository, timeline).run_once(NOW)
    assert len(timeline.requests) == 1
    assert {item.idempotency_key for item in timeline.requests} == {
        f"notification:{intent.intent_id}"
    }


@pytest.mark.asyncio
async def test_ambiguous_and_cancelled_intents_do_not_claim_delivery() -> None:
    sent = NotificationIntent.create(_draft(NotificationKind.DAILY_DIGEST), NOW)
    ambiguous = NotificationIntent.create(_draft(NotificationKind.MAIL_DIGEST), NOW)
    ambiguous.lease("owner", NOW + timedelta(seconds=30), NOW)
    ambiguous.mark_ambiguous("ProviderUnknown", NOW)
    cancelled = NotificationIntent.create(_draft(NotificationKind.MAIL_DIGEST), NOW)
    cancelled.lease("owner", NOW + timedelta(seconds=30), NOW)
    cancelled.cancel(NOW)
    repository = Repository([sent])
    repository.settled = [sent, ambiguous, cancelled]
    timeline = Timeline()

    await _service(repository, timeline).run_once(NOW)

    delivered_keys = {request.idempotency_key for request in timeline.requests}
    assert delivered_keys == {f"notification:{sent.intent_id}"}


@pytest.mark.asyncio
async def test_timeline_failure_does_not_break_delivery() -> None:
    intent = NotificationIntent.create(_draft(NotificationKind.DAILY_DIGEST), NOW)
    repository = Repository([intent])
    timeline = Timeline(failure=RuntimeError("timeline append failed"))

    delivered = await _service(repository, timeline).run_once(NOW)
    assert delivered == 1
    assert repository.saved == [NotificationIntentState.SENT]


@pytest.mark.asyncio
async def test_delivery_without_timeline_port_is_unchanged() -> None:
    intent = NotificationIntent.create(_draft(NotificationKind.DAILY_DIGEST), NOW)
    repository = Repository([intent])
    service = NotificationIntentDeliveryService(repository, Eligibility(), Sender(), "qq-1")

    assert await service.run_once(NOW) == 1
    assert repository.saved == [NotificationIntentState.SENT]
