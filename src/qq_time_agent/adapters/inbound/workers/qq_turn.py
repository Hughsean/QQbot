"""Crash recovery for a persisted QQ quiet-window turn."""

from contextlib import suppress
from datetime import datetime
from uuid import UUID

from qq_time_agent.adapters.inbound.workers.runner import (
    PermanentJobError,
    RetryableJobError,
)
from qq_time_agent.contracts.clock import Clock
from qq_time_agent.contracts.jobs import JobLease, JobQueue, JobRequest
from qq_time_agent.modules.agent.application import ConversationTurnCoordinator
from qq_time_agent.modules.agent.application.turn_input import (
    LoadedTurnSegment,
    build_turn_input,
)
from qq_time_agent.modules.agent.contracts import AgentRunCommandPort, AgentTurnTicket
from qq_time_agent.modules.inbox.contracts import InboxContentPort


class QqTurnJobHandler:
    def __init__(
        self,
        turns: ConversationTurnCoordinator,
        content: InboxContentPort,
        runs: AgentRunCommandPort,
        queue: JobQueue,
        clock: Clock,
    ) -> None:
        self._turns = turns
        self._content = content
        self._runs = runs
        self._queue = queue
        self._clock = clock

    async def __call__(self, job: JobLease) -> None:
        ticket = _ticket(job, self._clock.now())
        claim = await self._turns.settle(ticket)
        if claim is None:
            return
        try:
            loaded = []
            for ref in claim.segments:
                item = await self._content.get_content(ref.inbox_item_id)
                if item is None:
                    raise PermanentJobError("MissingAgentTurnSource")
                loaded.append(LoadedTurnSegment(ref, item.body_text))
            turn_input = build_turn_input(tuple(loaded))
            if turn_input is None:
                await self._turns.complete(claim)
                return
            current = claim.segments[-1]
            source_refs = tuple(f"inbox:{item_id}" for item_id in turn_input.related_inbox_item_ids)
            run = await self._runs.ensure_run(
                turn_input.command_inbox_item_id,
                "owner",
                current.source_type,
                conversation_key=f"qq-turn:{claim.conversation_key_hash}",
                occurred_at=current.occurred_at,
                message=turn_input.live_message,
                source_refs=source_refs,
            )
            await self._queue.enqueue(
                JobRequest(
                    "agent-run",
                    {
                        "run_id": str(run.run_id),
                        "inbox_item_id": str(turn_input.command_inbox_item_id),
                    },
                    f"agent-run:{run.run_id}",
                    self._clock.now(),
                )
            )
            await self._turns.complete(claim)
        except PermanentJobError as exc:
            with suppress(Exception):
                await self._turns.fail(claim, str(exc))
            raise
        except Exception as exc:
            with suppress(Exception):
                await self._turns.release(claim)
            raise RetryableJobError(type(exc).__name__) from exc


def _ticket(job: JobLease, now: datetime) -> AgentTurnTicket:
    raw_id = job.payload.get("turn_id")
    generation = job.payload.get("generation")
    if (
        not isinstance(raw_id, str)
        or isinstance(generation, bool)
        or not isinstance(generation, int)
    ):
        raise PermanentJobError("MalformedQqTurnPayload")
    try:
        turn_id = UUID(raw_id)
    except ValueError as exc:
        raise PermanentJobError("MalformedQqTurnPayload") from exc
    if generation < 1:
        raise PermanentJobError("MalformedQqTurnPayload")
    return AgentTurnTicket(turn_id, generation, now)
