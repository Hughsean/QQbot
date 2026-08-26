"""Durable Agent run contract."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from qq_time_agent.modules.agent.contracts.models import AgentDelivery


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


@dataclass(frozen=True, slots=True)
class ContextScope:
    conversation_id: UUID | None
    event_case_id: UUID | None


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
        limit: int,
    ) -> tuple[UUID, ...]: ...


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

    async def record_tool_call(
        self,
        run_id: UUID,
        call_id: str,
        tool_name: str,
        arguments_hash: str,
        observation: dict[str, object],
        now: datetime,
    ) -> None: ...
