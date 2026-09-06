"""Owner timeline event recorder for Notifications-originated deliveries."""

from qq_time_agent.contracts.clock import Clock
from qq_time_agent.modules.agent.contracts import (
    ConversationEventRepository,
    NotificationEventRequest,
)


class NotificationEventRecorder:
    """Implements the cross-module append port idempotently.

    A repeated request maps to the same idempotency key, so notification
    retries and concurrent QQ/Worker loops cannot duplicate timeline events.
    """

    def __init__(
        self,
        repository: ConversationEventRepository,
        clock: Clock,
    ) -> None:
        self._repository = repository
        self._clock = clock

    async def record_notification_event(self, request: NotificationEventRequest) -> None:
        await self._repository.append(request.to_event(), self._clock.now())
