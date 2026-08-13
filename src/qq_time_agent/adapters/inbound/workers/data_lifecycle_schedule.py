"""Stable hourly lifecycle job enqueue."""

from qq_time_agent.contracts.clock import Clock
from qq_time_agent.contracts.jobs import JobQueue, JobRequest


class DataLifecycleScheduler:
    def __init__(self, queue: JobQueue, clock: Clock) -> None:
        self._queue = queue
        self._clock = clock

    async def enqueue_due(self) -> None:
        now = self._clock.now()
        await self._queue.enqueue(
            JobRequest(
                "data-lifecycle-sweep",
                {},
                f"data-lifecycle:{now.strftime('%Y-%m-%dT%H')}",
                now,
                max_attempts=5,
            )
        )
