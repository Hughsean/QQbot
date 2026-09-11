from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from qq_time_agent.adapters.inbound.workers.conversation_summary import (
    ConversationSummaryJobHandler,
)
from qq_time_agent.adapters.inbound.workers.runner import PermanentJobError, RetryableJobError
from qq_time_agent.contracts.jobs import JobLease
from qq_time_agent.modules.agent.application.conversation_summary import (
    ConversationSummaryService,
    SummaryRequest,
)
from qq_time_agent.modules.agent.contracts import (
    ConversationEventRole,
    ConversationEventType,
    ConversationEventView,
    ConversationScopeType,
    ConversationSummaryView,
)

NOW = datetime(2026, 9, 10, 12, tzinfo=UTC)
SCOPE = uuid4()


@dataclass
class Clock:
    def now(self) -> datetime:
        return NOW


@dataclass
class Repository:
    events: tuple[ConversationEventView, ...]
    written: list[ConversationSummaryView] = field(default_factory=list)
    fail_write: bool = False

    async def list_snapshot_events(self, user_id, scope_type, scope_id, *, max_sequence, limit):
        del scope_id
        return tuple(
            event
            for event in self.events
            if event.user_id == user_id
            and event.scope_type is scope_type
            and event.sequence <= max_sequence
        )[-limit:]

    async def write_summary(self, request):
        if self.fail_write:
            raise RuntimeError("database unavailable")
        self.written.append(request.summary)
        return request.summary


def _event(sequence: int, event_type: ConversationEventType, content: str) -> ConversationEventView:
    return ConversationEventView(
        uuid4(),
        ConversationScopeType.CONVERSATION,
        SCOPE,
        "owner",
        sequence,
        event_type,
        ConversationEventRole.USER
        if event_type is ConversationEventType.USER_MESSAGE
        else ConversationEventRole.AGENT,
        NOW + timedelta(seconds=sequence),
        NOW + timedelta(seconds=sequence),
        content,
        "",
        "a" * 64,
        None,
        uuid4() if event_type is ConversationEventType.AGENT_REPLY else None,
        uuid4() if event_type is ConversationEventType.USER_MESSAGE else None,
        None,
        f"event:{sequence}",
        {},
    )


def _job(**payload: object) -> JobLease:
    return JobLease(uuid4(), "conversation-summary", payload, "worker", 1, 3)


@pytest.mark.asyncio
async def test_summary_service_writes_complete_turn_idempotently() -> None:
    repository = Repository(
        (
            _event(1, ConversationEventType.USER_MESSAGE, "需求"),
            _event(2, ConversationEventType.AGENT_REPLY, "答复"),
        )
    )
    service = ConversationSummaryService(repository, Clock())

    first = await service.summarize(SummaryRequest("owner", SCOPE, 1, 2))
    second = await service.summarize(SummaryRequest("owner", SCOPE, 1, 2))

    assert first == second
    assert len(repository.written) == 2
    assert first.from_sequence == 1 and first.to_sequence == 2
    assert first.facts == ("需求",)
    assert first.decisions == ("答复",)


@pytest.mark.asyncio
async def test_summary_service_rejects_incomplete_turn() -> None:
    repository = Repository((_event(1, ConversationEventType.USER_MESSAGE, "未完成"),))
    service = ConversationSummaryService(repository, Clock())

    with pytest.raises(ValueError, match="end with an agent reply"):
        await service.summarize(SummaryRequest("owner", SCOPE, 1, 1))


@pytest.mark.asyncio
async def test_summary_service_allows_global_sequence_gap_from_another_scope() -> None:
    repository = Repository(
        (
            _event(1, ConversationEventType.USER_MESSAGE, "需求"),
            _event(3, ConversationEventType.AGENT_REPLY, "答复"),
        )
    )
    service = ConversationSummaryService(repository, Clock())

    summary = await service.summarize(SummaryRequest("owner", SCOPE, 1, 3))

    assert (summary.from_sequence, summary.to_sequence) == (1, 3)


@pytest.mark.asyncio
async def test_summary_worker_classifies_payload_and_provider_failures() -> None:
    repository = Repository(
        (
            _event(1, ConversationEventType.USER_MESSAGE, "需求"),
            _event(2, ConversationEventType.AGENT_REPLY, "答复"),
        )
    )
    handler = ConversationSummaryJobHandler(
        ConversationSummaryService(repository, Clock()), Clock()
    )

    with pytest.raises(PermanentJobError, match="MalformedConversationSummaryPayload"):
        await handler(_job(user_id="owner", scope_id="bad", from_sequence=1, to_sequence=2))

    repository.fail_write = True
    with pytest.raises(RetryableJobError, match="ConversationSummaryUnavailable"):
        await handler(_job(user_id="owner", scope_id=str(SCOPE), from_sequence=1, to_sequence=2))
