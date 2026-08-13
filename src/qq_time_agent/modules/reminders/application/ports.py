"""Private Reminder persistence port."""

from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

from qq_time_agent.modules.reminders.domain.models import Reminder


class ReminderRepository(Protocol):
    async def add(self, reminder: Reminder) -> Reminder: ...

    async def get(self, reminder_id: UUID) -> Reminder | None: ...

    async def lease_due(
        self, now: datetime, worker_id: str, limit: int, lease_duration: timedelta
    ) -> tuple[Reminder, ...]: ...

    async def save(self, reminder: Reminder) -> None: ...

    async def list_for_entry(self, entry_id: UUID) -> tuple[Reminder, ...]: ...
