"""Private Notification delivery persistence port."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from qq_time_agent.modules.notifications.domain.models import (
    NotificationIntent,
    NotificationIntentDraft,
)


@dataclass(frozen=True, slots=True)
class StoredDelivery:
    idempotency_key: str
    delivery_id: str
    sent_at: datetime


class DeliveryRepository(Protocol):
    async def get(self, idempotency_key: str) -> StoredDelivery | None: ...

    async def record(self, delivery: StoredDelivery) -> StoredDelivery: ...


class NotificationEligibilityPort(Protocol):
    async def eligible_at(self, intent: NotificationIntent, now: datetime) -> datetime | None: ...


class NotificationIntentRepository(Protocol):
    async def add_or_get(
        self, draft: NotificationIntentDraft, now: datetime
    ) -> NotificationIntent: ...

    async def lease_due(
        self,
        now: datetime,
        owner: str,
        duration: timedelta,
        limit: int,
    ) -> tuple[NotificationIntent, ...]: ...

    async def save(self, intent: NotificationIntent, expected_version: int) -> None: ...

    async def has_open(self, subject_key: str) -> bool: ...

    async def has_recent_sent(self, subject_key: str, since: datetime) -> bool: ...

    async def recover_expired(self, now: datetime, limit: int) -> int: ...
