"""Idempotent discovery of normalized Inbox items for Understanding."""

from qq_time_agent.contracts.clock import Clock
from qq_time_agent.contracts.jobs import JobQueue, JobRequest
from qq_time_agent.modules.inbox.contracts import InboxProcessingQueryPort

UNDERSTANDING_JOB = "understanding-run"
UNDERSTANDING_WORKFLOW_VERSION = "v1"


class UnderstandingScheduler:
    def __init__(
        self,
        inbox: InboxProcessingQueryPort,
        queue: JobQueue,
        clock: Clock,
        batch_size: int = 50,
    ) -> None:
        if batch_size < 1 or batch_size > 100:
            raise ValueError("understanding scheduler batch must be between 1 and 100")
        self._inbox = inbox
        self._queue = queue
        self._clock = clock
        self._batch_size = batch_size

    async def enqueue_due(self) -> None:
        now = self._clock.now()
        for inbox_item_id in await self._inbox.list_normalized(self._batch_size):
            await self._queue.enqueue(
                JobRequest(
                    UNDERSTANDING_JOB,
                    {"inbox_item_id": str(inbox_item_id)},
                    f"understanding:{inbox_item_id}:{UNDERSTANDING_WORKFLOW_VERSION}",
                    now,
                    max_attempts=3,
                )
            )
