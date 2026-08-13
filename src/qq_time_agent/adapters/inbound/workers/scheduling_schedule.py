"""Idempotent discovery of candidates awaiting a Scheduling Proposal."""

from qq_time_agent.adapters.inbound.workers.scheduling import SchedulingCandidateSource
from qq_time_agent.contracts.clock import Clock
from qq_time_agent.contracts.jobs import JobQueue, JobRequest

SCHEDULING_JOB = "scheduling-propose"
SCHEDULING_VERSION = "v1"


class SchedulingScheduler:
    def __init__(
        self,
        candidates: SchedulingCandidateSource,
        queue: JobQueue,
        clock: Clock,
        batch_size: int = 50,
    ) -> None:
        if batch_size < 1 or batch_size > 100:
            raise ValueError("scheduling batch must be between 1 and 100")
        self._candidates = candidates
        self._queue = queue
        self._clock = clock
        self._batch_size = batch_size

    async def enqueue_due(self) -> None:
        now = self._clock.now()
        for candidate_id in await self._candidates.list_candidate_ids(self._batch_size):
            await self._queue.enqueue(
                JobRequest(
                    SCHEDULING_JOB,
                    {"candidate_id": str(candidate_id)},
                    f"scheduling:{candidate_id}:{SCHEDULING_VERSION}",
                    now,
                    max_attempts=3,
                )
            )
