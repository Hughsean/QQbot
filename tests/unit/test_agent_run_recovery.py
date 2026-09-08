from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from qq_time_agent.contracts.tools import ToolDefinition
from qq_time_agent.modules.agent.application.loop import AgentLoop
from qq_time_agent.modules.agent.application.run_service import AgentRunService
from qq_time_agent.modules.agent.contracts import (
    AgentFinal,
    AgentResponse,
    AgentRun,
    AgentRunClaim,
    AgentRunStatus,
    AgentToolCall,
    ConversationSnapshot,
    ToolObservation,
)


class Clock:
    def now(self) -> datetime:
        return datetime(2026, 8, 27, tzinfo=UTC)


@dataclass
class Model:
    responses: list[AgentResponse | Exception]

    async def respond(self, request: object) -> AgentResponse:
        del request
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


@dataclass
class Tools:
    calls: int = 0

    def definitions(self) -> tuple[ToolDefinition, ...]:
        return (ToolDefinition("update_agenda", "test", {"type": "object", "properties": {}}),)

    async def call(
        self,
        owner_id: str,
        name: str,
        arguments: dict[str, object],
        context: object,
    ) -> object:
        del context
        assert owner_id == "owner" and name == "update_agenda" and arguments == {}
        self.calls += 1
        return {"status": "SUCCEEDED"}


@dataclass
class Repository:
    run: AgentRun
    snapshots: list[ConversationSnapshot] = field(default_factory=list)

    async def get(self, run_id: UUID) -> AgentRun | None:
        return self.run if run_id == self.run.run_id else None

    async def save(self, run: AgentRun, expected_version: int) -> None:
        assert expected_version == self.run.version
        run.version += 1
        self.run = run

    async def checkpoint_tool_call(
        self, run_id: UUID, observation: ToolObservation, now: datetime
    ) -> None:
        assert run_id == self.run.run_id
        self.run.observations.append(
            {
                "call_id": observation.call_id,
                "name": observation.name,
                "output": str(observation.output),
                "is_error": observation.is_error,
                "arguments_hash": observation.arguments_hash,
            }
        )
        self.run.step = len(self.run.observations)
        self.run.updated_at = now
        self.run.version += 1

    async def record_context_snapshot(self, run_id: UUID, snapshot: ConversationSnapshot) -> None:
        assert run_id == self.run.run_id
        if self.snapshots and self.snapshots[-1] != snapshot:
            raise ValueError("snapshot changed")
        self.snapshots.append(snapshot)
        self.run.context_revision = snapshot.revision
        self.run.context_max_sequence = snapshot.max_sequence
        self.run.context_hash = snapshot.context_hash

    async def claim(
        self,
        run_id: UUID,
        execution_owner: str,
        now: datetime,
        lease_until: datetime,
    ) -> AgentRunClaim | None:
        del now
        if self.run.status is AgentRunStatus.COMPLETED:
            return None
        self.run.status = AgentRunStatus.RUNNING
        self.run.execution_owner = execution_owner
        self.run.execution_lease_until = lease_until
        self.run.execution_epoch += 1
        self.run.version += 1
        return AgentRunClaim(self.run, execution_owner, self.run.execution_epoch, lease_until)

    async def renew_claim(
        self, claim: AgentRunClaim, now: datetime, lease_until: datetime
    ) -> AgentRunClaim:
        del now
        self.run.execution_lease_until = lease_until
        self.run.version += 1
        return AgentRunClaim(self.run, claim.execution_owner, claim.execution_epoch, lease_until)

    async def checkpoint_claimed_tool_call(
        self, claim: AgentRunClaim, observation: ToolObservation, now: datetime
    ) -> AgentRunClaim:
        await self.checkpoint_tool_call(claim.run.run_id, observation, now)
        return claim

    async def complete_claim(
        self, claim: AgentRunClaim, result: AgentFinal, now: datetime
    ) -> AgentRun:
        self.run.status = AgentRunStatus.COMPLETED
        self.run.final_content = result.content
        self.run.final_delivery = result.delivery
        self.run.completed_at = now
        self.run.updated_at = now
        self.run.execution_owner = None
        self.run.execution_lease_until = None
        self.run.version += 1
        return self.run

    async def fail_claim(self, claim: AgentRunClaim, failure_class: str, now: datetime) -> AgentRun:
        del claim
        self.run.status = AgentRunStatus.FAILED
        self.run.failure_class = failure_class
        self.run.updated_at = now
        self.run.execution_owner = None
        self.run.execution_lease_until = None
        self.run.version += 1
        return self.run


@pytest.mark.asyncio
async def test_recovery_reuses_checkpointed_tool_observation_without_repeating_call() -> None:
    run = AgentRun(uuid4(), uuid4(), "owner", "QQ_DIRECT", AgentRunStatus.PENDING, 0)
    repository = Repository(run)
    tools = Tools()
    model = Model(
        [
            AgentResponse(tool_call=AgentToolCall("call-1", "update_agenda", {})),
            RuntimeError("interrupted"),
            AgentResponse(tool_call=AgentToolCall("call-1", "update_agenda", {})),
            AgentResponse(final=AgentFinal("已更新")),
        ]
    )
    service = AgentRunService(repository, AgentLoop(model, tools), Clock())  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="interrupted"):
        await service.execute(run.run_id, "更新日程")
    assert tools.calls == 1, repository.run.observations
    assert len(repository.run.observations) == 1
    result = await service.execute(run.run_id, "更新日程")

    assert result.content == "已更新"
    assert tools.calls == 1
    assert len(repository.run.observations) == 1


@pytest.mark.asyncio
async def test_snapshot_persistence_failure_stops_model_execution() -> None:
    class FailingRepository(Repository):
        async def record_context_snapshot(
            self, run_id: UUID, snapshot: ConversationSnapshot
        ) -> None:
            del run_id, snapshot
            raise RuntimeError("snapshot unavailable")

    run = AgentRun(uuid4(), uuid4(), "owner", "QQ_DIRECT", AgentRunStatus.PENDING, 0)
    repository = FailingRepository(run)
    model = Model([AgentResponse(final=AgentFinal("不应执行"))])
    service = AgentRunService(repository, AgentLoop(model, Tools()), Clock())  # type: ignore[arg-type]
    snapshot = ConversationSnapshot("owner", uuid4(), 7, 7, "a" * 64)

    with pytest.raises(RuntimeError, match="snapshot unavailable"):
        await service.execute(run.run_id, "继续", snapshot=snapshot)

    assert model.responses == [AgentResponse(final=AgentFinal("不应执行"))]
    assert repository.run.status is AgentRunStatus.FAILED


@pytest.mark.asyncio
async def test_retry_reuses_same_pinned_snapshot_hash() -> None:
    run = AgentRun(uuid4(), uuid4(), "owner", "QQ_DIRECT", AgentRunStatus.PENDING, 0)
    repository = Repository(run)
    snapshot = ConversationSnapshot("owner", uuid4(), 9, 9, "b" * 64)
    model = Model([RuntimeError("interrupted"), AgentResponse(final=AgentFinal("已恢复"))])
    service = AgentRunService(repository, AgentLoop(model, Tools()), Clock())  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="interrupted"):
        await service.execute(run.run_id, "继续", snapshot=snapshot)
    result = await service.execute(run.run_id, "继续", snapshot=snapshot)

    assert result.content == "已恢复"
    assert repository.snapshots == [snapshot]
    assert (repository.run.context_max_sequence, repository.run.context_hash) == (9, "b" * 64)


@pytest.mark.asyncio
async def test_snapshot_is_persisted_before_execution_and_reused_on_retry() -> None:
    run = AgentRun(uuid4(), uuid4(), "owner", "QQ_DIRECT", AgentRunStatus.PENDING, 0)
    repository = Repository(run)
    snapshot = ConversationSnapshot("owner", uuid4(), 7, 7, "a" * 64)
    model = Model([RuntimeError("interrupted"), AgentResponse(final=AgentFinal("已恢复"))])
    service = AgentRunService(repository, AgentLoop(model, Tools()), Clock())  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="interrupted"):
        await service.execute(run.run_id, "继续", snapshot=snapshot)
    result = await service.execute(run.run_id, "继续", snapshot=snapshot)

    assert result.content == "已恢复"
    assert repository.snapshots == [snapshot]
    assert repository.run.context_revision == snapshot.revision
    assert repository.run.context_max_sequence == snapshot.max_sequence
    assert repository.run.context_hash == snapshot.context_hash
