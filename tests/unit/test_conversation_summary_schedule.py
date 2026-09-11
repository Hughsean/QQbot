from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from qq_time_agent.adapters.inbound.workers.conversation_summary_schedule import (
    ConversationSummaryScheduler,
)
from qq_time_agent.contracts.jobs import JobRequest
from qq_time_agent.modules.agent.contracts import ConversationSummaryCandidate

NOW = datetime(2026, 9, 10, 12, tzinfo=UTC)


@dataclass
class Clock:
    def now(self) -> datetime:
        return NOW


@dataclass
class Query:
    candidates: tuple[ConversationSummaryCandidate, ...]
    calls: list[tuple[str, int, int]] = field(default_factory=list)

    async def list_summary_candidates(self, user_id, *, protected_turns, limit):
        self.calls.append((user_id, protected_turns, limit))
        return self.candidates


@dataclass
class Queue:
    requests: list[JobRequest] = field(default_factory=list)

    async def enqueue(self, request: JobRequest):
        self.requests.append(request)
        return uuid4()


@pytest.mark.asyncio
async def test_summary_scheduler_enqueues_deterministic_idempotent_jobs() -> None:
    candidate = ConversationSummaryCandidate("owner", uuid4(), 1, 2)
    query = Query((candidate,))
    queue = Queue()

    await ConversationSummaryScheduler(query, queue, Clock()).enqueue_due()
    await ConversationSummaryScheduler(query, queue, Clock()).enqueue_due()

    assert query.calls == [("owner", 8, 20), ("owner", 8, 20)]
    assert len(queue.requests) == 2
    assert queue.requests[0].idempotency_key == queue.requests[1].idempotency_key
    assert queue.requests[0].payload == {
        "user_id": "owner",
        "scope_id": str(candidate.scope_id),
        "from_sequence": 1,
        "to_sequence": 2,
    }


def test_summary_scheduler_rejects_invalid_protected_turns() -> None:
    with pytest.raises(ValueError, match="limits"):
        ConversationSummaryScheduler(Query(()), Queue(), Clock(), protected_turns=5)
