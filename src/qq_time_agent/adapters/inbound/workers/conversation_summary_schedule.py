"""Periodic discovery of old complete turns eligible for summarization."""

from qq_time_agent.contracts.clock import Clock
from qq_time_agent.contracts.jobs import JobQueue, JobRequest
from qq_time_agent.modules.agent.contracts import ConversationSummaryCandidateQueryPort


class ConversationSummaryScheduler:
    def __init__(
        self,
        query: ConversationSummaryCandidateQueryPort,
        queue: JobQueue,
        clock: Clock,
        user_id: str = "owner",
        protected_turns: int = 8,
        batch_size: int = 20,
    ) -> None:
        if not user_id.strip() or not 6 <= protected_turns <= 12 or not 1 <= batch_size <= 100:
            raise ValueError("conversation summary scheduler limits are invalid")
        self._query = query
        self._queue = queue
        self._clock = clock
        self._user_id = user_id
        self._protected_turns = protected_turns
        self._batch_size = batch_size

    async def enqueue_due(self) -> None:
        now = self._clock.now()
        candidates = await self._query.list_summary_candidates(
            self._user_id, protected_turns=self._protected_turns, limit=self._batch_size
        )
        for candidate in candidates:
            await self._queue.enqueue(
                JobRequest(
                    "conversation-summary",
                    {
                        "user_id": candidate.user_id,
                        "scope_id": str(candidate.scope_id),
                        "from_sequence": candidate.from_sequence,
                        "to_sequence": candidate.to_sequence,
                    },
                    (
                        f"conversation-summary:{candidate.user_id}:{candidate.scope_id}:"
                        f"{candidate.from_sequence}:{candidate.to_sequence}"
                    ),
                    now,
                    max_attempts=5,
                )
            )
