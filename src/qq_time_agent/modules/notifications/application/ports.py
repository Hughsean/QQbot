"""Private Notification delivery persistence port."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class StoredDelivery:
    idempotency_key: str
    delivery_id: str
    sent_at: datetime


class DeliveryRepository(Protocol):
    async def get(self, idempotency_key: str) -> StoredDelivery | None: ...

    async def record(self, delivery: StoredDelivery) -> StoredDelivery: ...
