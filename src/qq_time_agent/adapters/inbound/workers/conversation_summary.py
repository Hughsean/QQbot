"""Durable worker handler for deterministic conversation summaries."""

from uuid import UUID

from qq_time_agent.adapters.inbound.workers.runner import PermanentJobError, RetryableJobError
from qq_time_agent.contracts.clock import Clock
from qq_time_agent.contracts.jobs import JobLease
from qq_time_agent.modules.agent.application.conversation_summary import (
    ConversationSummaryService,
    SummaryRequest,
)


class ConversationSummaryJobHandler:
    def __init__(self, service: ConversationSummaryService, clock: Clock) -> None:
        self._service = service
        self._clock = clock

    async def __call__(self, job: JobLease) -> None:
        try:
            user_id = job.payload["user_id"]
            scope_id = UUID(str(job.payload["scope_id"]))
            from_sequence = _sequence(job.payload["from_sequence"])
            to_sequence = _sequence(job.payload["to_sequence"])
        except (KeyError, TypeError, ValueError) as exc:
            raise PermanentJobError("MalformedConversationSummaryPayload") from exc
        if not isinstance(user_id, str) or not user_id.strip():
            raise PermanentJobError("MalformedConversationSummaryPayload")
        try:
            await self._service.summarize(
                SummaryRequest(user_id, scope_id, from_sequence, to_sequence)
            )
        except ValueError as exc:
            raise PermanentJobError("InvalidConversationSummarySource") from exc
        except Exception as exc:
            raise RetryableJobError("ConversationSummaryUnavailable") from exc


def _sequence(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError("sequence must be positive")
    if isinstance(value, int):
        result = value
    elif isinstance(value, str):
        result = int(value)
    else:
        raise ValueError("sequence must be positive")
    if result < 1:
        raise ValueError("sequence must be positive")
    return result
