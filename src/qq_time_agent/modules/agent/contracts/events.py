"""Provider-neutral, redacted AgentRun execution events."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID, uuid4


class AgentRunEventType(StrEnum):
    RUN_CREATED = "RUN_CREATED"
    RUN_CLAIMED = "RUN_CLAIMED"
    ROUND_STARTED = "ROUND_STARTED"
    MODEL_REQUEST = "MODEL_REQUEST"
    MODEL_RESULT = "MODEL_RESULT"
    TOOL_CALL_STARTED = "TOOL_CALL_STARTED"
    TOOL_RESULT = "TOOL_RESULT"
    CHECKPOINT = "CHECKPOINT"
    RETRY = "RETRY"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class AgentRunEvent:
    run_id: UUID
    event_type: AgentRunEventType
    occurred_at: datetime
    step: int = 0
    status: str | None = None
    duration_ms: int | None = None
    error_class: str | None = None
    tool_name: str | None = None
    call_id: str | None = None
    invocation_id: UUID | None = None
    idempotency_key: str = ""
    metadata: Mapping[str, object] = field(default_factory=dict)
    event_id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("AgentRun event time must be timezone-aware")
        if self.step < 0 or (self.duration_ms is not None and self.duration_ms < 0):
            raise ValueError("AgentRun event numeric fields are invalid")
        if not self.idempotency_key.strip():
            raise ValueError("AgentRun event idempotency key is required")
        if len(self.metadata) > 32:
            raise ValueError("AgentRun event metadata is too large")


@dataclass(frozen=True, slots=True)
class AgentRunEventView:
    event_id: UUID
    run_id: UUID
    event_type: AgentRunEventType
    occurred_at: datetime
    step: int
    status: str | None
    duration_ms: int | None
    error_class: str | None
    tool_name: str | None
    call_id: str | None
    invocation_id: UUID | None
    metadata: dict[str, object]


class AgentRunEventRepository(Protocol):
    async def append(self, event: AgentRunEvent) -> AgentRunEventView: ...

    async def list_for_run(
        self, run_id: UUID, limit: int = 500
    ) -> tuple[AgentRunEventView, ...]: ...

    async def list_for_scope(
        self, scope_id: UUID, scope_type: str, limit: int = 500
    ) -> tuple[AgentRunEventView, ...]: ...
