"""Periodic Worker-side generation of durable notification intents."""

from datetime import datetime, timedelta
from typing import Protocol

from qq_time_agent.contracts.clock import Clock


class NotificationPlanner(Protocol):
    async def plan(self, user_id: str, now: datetime) -> int: ...


class NotificationPlanningScheduler:
    def __init__(
        self,
        planner: NotificationPlanner,
        clock: Clock,
        user_id: str = "owner",
        interval: timedelta = timedelta(minutes=1),
    ) -> None:
        self._planner = planner
        self._clock = clock
        self._user_id = user_id
        self._interval = interval
        self._next_at: datetime | None = None

    async def enqueue_due(self) -> None:
        now = self._clock.now()
        if self._next_at is not None and now < self._next_at:
            return
        await self._planner.plan(self._user_id, now)
        self._next_at = now + self._interval
