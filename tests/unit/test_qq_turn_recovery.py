from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from qq_time_agent.adapters.inbound.workers.qq_turn import QqTurnJobHandler
from qq_time_agent.adapters.inbound.workers.runner import PermanentJobError
from qq_time_agent.contracts.jobs import JobLease, JobRequest
from qq_time_agent.modules.agent.contracts import (
    AgentRun,
    AgentRunStatus,
    AgentTurnClaim,
    AgentTurnSegmentRef,
)
from qq_time_agent.modules.inbox.contracts import InboxContentView

NOW = datetime(2026, 9, 14, tzinfo=UTC)


class Clock:
    def now(self) -> datetime:
        return NOW


@dataclass
class Turns:
    claim: AgentTurnClaim | None
    completed: int = 0
    released: int = 0
    failed: int = 0

    async def settle(self, ticket: object) -> AgentTurnClaim | None:
        del ticket
        return self.claim

    async def complete(self, claim: AgentTurnClaim) -> None:
        assert claim == self.claim
        self.completed += 1

    async def release(self, claim: AgentTurnClaim) -> None:
        assert claim == self.claim
        self.released += 1

    async def fail(self, claim: AgentTurnClaim, failure_class: str) -> None:
        assert claim == self.claim and failure_class
        self.failed += 1


@dataclass
class Content:
    values: dict[UUID, InboxContentView]

    async def get_content(self, inbox_item_id: UUID) -> InboxContentView | None:
        return self.values.get(inbox_item_id)


@dataclass
class Runs:
    captured: dict[str, object] = field(default_factory=dict)

    async def ensure_run(
        self,
        inbox_item_id: UUID,
        user_id: str,
        source_type: str,
        conversation_key: str | None = None,
        event_key: str | None = None,
        occurred_at: datetime | None = None,
        message: str | None = None,
        source_refs: tuple[str, ...] = (),
    ) -> AgentRun:
        self.captured = {
            "inbox_item_id": inbox_item_id,
            "user_id": user_id,
            "source_type": source_type,
            "conversation_key": conversation_key,
            "event_key": event_key,
            "occurred_at": occurred_at,
            "message": message,
            "source_refs": source_refs,
        }
        return AgentRun(uuid4(), inbox_item_id, user_id, source_type, AgentRunStatus.PENDING, 0)


@dataclass
class Queue:
    values: list[JobRequest] = field(default_factory=list)

    async def enqueue(self, request: JobRequest) -> UUID:
        self.values.append(request)
        return uuid4()


def _item(item_id: UUID, body: str) -> InboxContentView:
    return InboxContentView(
        item_id,
        "QQ 输入",
        body,
        None,
        "text/plain",
        NOW,
        f"qq:{item_id}",
        "hash",
        None,
    )


def _job(turn_id: UUID, generation: int = 2) -> JobLease:
    return JobLease(
        uuid4(),
        "qq-turn",
        {"turn_id": str(turn_id), "generation": generation},
        "worker",
        1,
        5,
    )


@pytest.mark.asyncio
async def test_recovery_creates_one_run_from_material_and_short_command() -> None:
    turn_id, material_id, command_id = uuid4(), uuid4(), uuid4()
    refs = (
        AgentTurnSegmentRef(material_id, 1, "QQ_DIRECT", "T1", NOW, 1, None, 100),
        AgentTurnSegmentRef(
            command_id,
            2,
            "QQ_DIRECT",
            "T1",
            NOW + timedelta(milliseconds=500),
            2,
            None,
            4,
        ),
    )
    claim = AgentTurnClaim(turn_id, 2, "a" * 64, "worker", refs)
    turns, runs, queue = Turns(claim), Runs(), Queue()
    handler = QqTurnJobHandler(
        turns,
        Content(
            {
                material_id: _item(material_id, "9月16日下午2:30在报告厅"),
                command_id: _item(command_id, "创建日程"),
            }
        ),
        runs,
        queue,
        Clock(),
    )

    await handler(_job(turn_id))

    assert runs.captured["message"] == "创建日程"
    assert runs.captured["source_refs"] == (f"inbox:{material_id}",)
    assert runs.captured["conversation_key"] == f"qq-turn:{'a' * 64}"
    assert queue.values[0].kind == "agent-run"
    assert turns.completed == 1


@pytest.mark.asyncio
async def test_superseded_recovery_job_does_nothing() -> None:
    turns, runs, queue = Turns(None), Runs(), Queue()
    await QqTurnJobHandler(turns, Content({}), runs, queue, Clock())(_job(uuid4()))
    assert runs.captured == {} and queue.values == []


@pytest.mark.asyncio
async def test_malformed_recovery_payload_is_permanent() -> None:
    job = _job(uuid4())
    job.payload["generation"] = 0
    with pytest.raises(PermanentJobError, match="MalformedQqTurnPayload"):
        await QqTurnJobHandler(Turns(None), Content({}), Runs(), Queue(), Clock())(job)
