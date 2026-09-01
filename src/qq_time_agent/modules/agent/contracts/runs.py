"""Durable Agent run contract."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from qq_time_agent.modules.agent.contracts.models import (
    AgentDelivery,
    AgentFinal,
    ToolObservation,
)


class AgentRunStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass(slots=True)
class AgentRun:
    run_id: UUID
    inbox_item_id: UUID
    user_id: str
    source_type: str
    status: AgentRunStatus
    step: int
    observations: list[dict[str, object]] = field(default_factory=list)
    final_content: str | None = None
    final_delivery: AgentDelivery | None = None
    failure_class: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    version: int = 1
    conversation_id: UUID | None = None
    event_case_id: UUID | None = None
    execution_owner: str | None = None
    execution_lease_until: datetime | None = None
    execution_epoch: int = 0
    effective_delivery: AgentDelivery | None = None


@dataclass(frozen=True, slots=True)
class AgentRunClaim:
    run: AgentRun
    execution_owner: str
    execution_epoch: int
    lease_until: datetime


class AgentRunClaimError(RuntimeError):
    """The caller no longer owns the AgentRun execution fence."""


class AgentRunExecutionStatus(StrEnum):
    COMPLETED = "COMPLETED"
    EXECUTED = "EXECUTED"
    IN_PROGRESS = "IN_PROGRESS"


@dataclass(frozen=True, slots=True)
class AgentRunExecution:
    status: AgentRunExecutionStatus
    final: AgentFinal | None = None

    def __post_init__(self) -> None:
        if (self.status is AgentRunExecutionStatus.IN_PROGRESS) != (self.final is None):
            raise ValueError("AgentRun execution outcome is inconsistent")

    @property
    def content(self) -> str:
        if self.final is None:
            raise RuntimeError("AgentRun execution is still in progress")
        return self.final.content

    @property
    def delivery(self) -> AgentDelivery:
        if self.final is None:
            raise RuntimeError("AgentRun execution is still in progress")
        return self.final.delivery


@dataclass(frozen=True, slots=True)
class MailRunSummary:
    run_id: UUID
    inbox_item_id: UUID
    source_type: str
    summary: str
    completed_at: datetime


class MailRunSummaryQueryPort(Protocol):
    async def list_recent_mail_summaries(
        self, user_id: str, since: datetime, limit: int = 20
    ) -> tuple[MailRunSummary, ...]: ...


@dataclass(frozen=True, slots=True)
class ContextScope:
    conversation_id: UUID | None
    event_case_id: UUID | None




@dataclass(frozen=True, slots=True)
class ScopedAgentReply:
    run_id: UUID
    content: str
    occurred_at: datetime


class AgentContextRepository(Protocol):
    async def ensure_scope(
        self,
        user_id: str,
        conversation_key: str | None,
        event_key: str | None,
        now: datetime,
    ) -> ContextScope: ...

    async def attach_item(
        self,
        scope: ContextScope,
        inbox_item_id: UUID,
        occurred_at: datetime,
    ) -> None: ...

    async def list_item_ids(
        self,
        scope_id: UUID,
        scope_type: str,
        exclude_id: UUID,
        before: datetime,
        limit: int,
    ) -> tuple[UUID, ...]: ...

    async def list_final_replies(
        self,
        scope_id: UUID,
        scope_type: str,
        before: datetime,
        limit: int,
    ) -> tuple[ScopedAgentReply, ...]: ...


class AgentRunRepository(Protocol):
    async def get_or_create(
        self,
        inbox_item_id: UUID,
        user_id: str,
        source_type: str,
        now: datetime,
        scope: ContextScope | None = None,
    ) -> AgentRun: ...

    async def get(self, run_id: UUID) -> AgentRun | None: ...

    async def save(self, run: AgentRun, expected_version: int) -> None: ...

    async def freeze_effective_delivery(
        self, run_id: UUID, delivery: AgentDelivery
    ) -> AgentDelivery: ...

    async def claim(
        self,
        run_id: UUID,
        execution_owner: str,
        now: datetime,
        lease_until: datetime,
    ) -> AgentRunClaim | None: ...

    async def renew_claim(
        self,
        claim: AgentRunClaim,
        now: datetime,
        lease_until: datetime,
    ) -> AgentRunClaim: ...

    async def checkpoint_claimed_tool_call(
        self,
        claim: AgentRunClaim,
        observation: ToolObservation,
        now: datetime,
    ) -> AgentRunClaim: ...

    async def complete_claim(
        self,
        claim: AgentRunClaim,
        result: AgentFinal,
        now: datetime,
    ) -> AgentRun: ...

    async def fail_claim(
        self,
        claim: AgentRunClaim,
        failure_class: str,
        now: datetime,
    ) -> AgentRun: ...

    async def checkpoint_tool_call(
        self,
        run_id: UUID,
        observation: ToolObservation,
        now: datetime,
    ) -> None: ...
