"""Lease-based active notification delivery orchestration."""

import logging
from datetime import datetime, timedelta

from qq_time_agent.modules.agent.contracts import (
    ConversationDeliveryStatus,
    ConversationEventType,
    NotificationEventCommandPort,
    NotificationEventRequest,
)
from qq_time_agent.modules.notifications.application.ports import (
    NotificationEligibilityPort,
    NotificationIntentRepository,
)
from qq_time_agent.modules.notifications.application.rendering import render_outbound
from qq_time_agent.modules.notifications.contracts import (
    NotificationPreSendPermanentError,
    NotificationPreSendTransientError,
    NotificationSender,
)
from qq_time_agent.modules.notifications.domain.models import (
    NotificationIntent,
    NotificationIntentState,
    NotificationKind,
)

LOGGER = logging.getLogger(__name__)

_EVENT_TYPE_BY_KIND: dict[NotificationKind, ConversationEventType] = {
    NotificationKind.DAILY_DIGEST: ConversationEventType.DAILY_DIGEST,
    NotificationKind.MAIL_DIGEST: ConversationEventType.MAIL_DIGEST,
    NotificationKind.OUTLOOK_MAIL_RESULT: ConversationEventType.MAIL_NOTIFICATION,
    NotificationKind.QQ_MAIL_RESULT: ConversationEventType.MAIL_NOTIFICATION,
    NotificationKind.AGENT_RESULT: ConversationEventType.MAIL_NOTIFICATION,
    NotificationKind.AGENDA_CONFLICT: ConversationEventType.SYSTEM_RESULT,
    NotificationKind.CONNECTION_REAUTH: ConversationEventType.SYSTEM_RESULT,
}


class NotificationIntentDeliveryService:
    def __init__(
        self,
        repository: NotificationIntentRepository,
        eligibility: NotificationEligibilityPort,
        sender: NotificationSender,
        lease_owner: str,
        lease_duration: timedelta = timedelta(seconds=30),
        timeline: NotificationEventCommandPort | None = None,
        timeline_window: timedelta = timedelta(minutes=15),
        timeline_limit: int = 50,
    ) -> None:
        self._repository = repository
        self._eligibility = eligibility
        self._sender = sender
        self._lease_owner = lease_owner
        self._lease_duration = lease_duration
        self._timeline = timeline
        self._timeline_window = timeline_window
        self._timeline_limit = timeline_limit

    async def run_once(self, now: datetime, limit: int = 20) -> int:
        await self._repository.recover_expired(now, limit)
        values = await self._repository.lease_due(
            now, self._lease_owner, self._lease_duration, limit
        )
        delivered = 0
        for value in values:
            expected = value.version
            try:
                eligible_at = await self._eligibility.eligible_at(value, now)
            except Exception as exc:
                delay = timedelta(seconds=min(60, 2**value.attempt_count))
                value.mark_pre_send_failure(type(exc).__name__, now, now + delay, 3)
                await self._repository.save(value, expected)
                continue
            if eligible_at is None:
                value.cancel(now)
                await self._repository.save(value, expected)
                continue
            if eligible_at > now:
                value.defer(eligible_at, now)
                await self._repository.save(value, expected)
                continue
            try:
                delivery_id = await self._sender.send_active(
                    render_outbound(value.draft.kind, value.draft.content)
                )
            except NotificationPreSendTransientError as exc:
                delay = timedelta(seconds=min(60, 2**value.attempt_count))
                value.mark_pre_send_failure(type(exc).__name__, now, now + delay, 3)
                await self._repository.save(value, expected)
                continue
            except NotificationPreSendPermanentError as exc:
                value.mark_pre_send_failure(type(exc).__name__, now, None, 3)
                await self._repository.save(value, expected)
                continue
            except Exception as exc:
                value.mark_ambiguous(type(exc).__name__, now)
                await self._repository.save(value, expected)
                continue
            value.mark_sent(delivery_id, now)
            await self._repository.save(value, expected)
            delivered += 1
        if self._timeline is not None:
            await self._reconcile_timeline_events(now)
        return delivered

    async def _reconcile_timeline_events(self, now: datetime) -> None:
        """Idempotently mirror settled intents into the owner timeline.

        Re-running this each cycle retries lost appends without duplicating
        events: the idempotency key is derived from the intent id alone, so a
        notification retry never creates a second timeline event.
        """
        assert self._timeline is not None
        settled = await self._repository.list_recently_settled(
            now - self._timeline_window, self._timeline_limit
        )
        for intent in settled:
            request = _timeline_request(intent)
            if request is None:
                continue
            try:
                await self._timeline.record_notification_event(request)
            except Exception as exc:
                LOGGER.warning(
                    "通知时间线事件写入失败: 将在后续周期幂等重试",
                    extra={
                        "role": "notifications",
                        "intent_id": str(intent.intent_id),
                        "kind": intent.draft.kind.value,
                        "failure_class": type(exc).__name__,
                    },
                )


def _timeline_request(intent: NotificationIntent) -> NotificationEventRequest | None:
    event_type = _EVENT_TYPE_BY_KIND.get(intent.draft.kind)
    if event_type is None:
        return None
    if intent.state is NotificationIntentState.SENT:
        status = ConversationDeliveryStatus.DELIVERED
        occurred_at = intent.sent_at
    elif intent.state is NotificationIntentState.DEAD_LETTER:
        status = ConversationDeliveryStatus.FAILED
        occurred_at = intent.updated_at
    else:
        return None
    if occurred_at is None:
        return None
    return NotificationEventRequest(
        user_id=intent.draft.user_id,
        event_type=event_type,
        notification_intent_id=intent.intent_id,
        content=render_outbound(intent.draft.kind, intent.draft.content),
        delivery_status=status,
        occurred_at=occurred_at,
        idempotency_key=f"notification:{intent.intent_id}",
    )
