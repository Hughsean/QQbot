"""Lease-based active notification delivery orchestration."""

from datetime import datetime, timedelta

from qq_time_agent.modules.notifications.application.ports import (
    NotificationEligibilityPort,
    NotificationIntentRepository,
)
from qq_time_agent.modules.notifications.contracts import (
    NotificationPreSendPermanentError,
    NotificationPreSendTransientError,
    NotificationSender,
)


class NotificationIntentDeliveryService:
    def __init__(
        self,
        repository: NotificationIntentRepository,
        eligibility: NotificationEligibilityPort,
        sender: NotificationSender,
        lease_owner: str,
        lease_duration: timedelta = timedelta(seconds=30),
    ) -> None:
        self._repository = repository
        self._eligibility = eligibility
        self._sender = sender
        self._lease_owner = lease_owner
        self._lease_duration = lease_duration

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
                delivery_id = await self._sender.send_active(value.draft.content)
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
        return delivered
