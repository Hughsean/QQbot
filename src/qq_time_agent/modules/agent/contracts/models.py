"""Provider-neutral contracts for a bounded tool-calling Agent loop."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from qq_time_agent.contracts.tools import ToolCallContext, ToolDefinition

if TYPE_CHECKING:
    from qq_time_agent.modules.agent.contracts.runs import AgentRun, AgentRunExecution

AgentToolDefinition = ToolDefinition


class AgentResponseProtocolError(ValueError):
    """The model produced JSON outside the Agent response protocol."""


@dataclass(frozen=True, slots=True)
class AgentToolCall:
    call_id: str
    name: str
    arguments: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class ToolObservation:
    call_id: str
    name: str
    output: object
    is_error: bool = False
    arguments_hash: str = ""


class AgentResponseMode(StrEnum):
    TOOL_OR_FINAL = "TOOL_OR_FINAL"
    FINAL_ONLY = "FINAL_ONLY"


@dataclass(frozen=True, slots=True)
class AgentRequest:
    system_instruction: str
    user_message: str
    context: str
    tools: tuple[AgentToolDefinition, ...]
    observations: tuple[ToolObservation, ...]
    step: int
    owner_timezone: str = "Asia/Shanghai"
    reference_time: datetime | None = None
    max_output_tokens: int = 1200
    response_mode: AgentResponseMode = AgentResponseMode.TOOL_OR_FINAL

    def __post_init__(self) -> None:
        if self.max_output_tokens < 1:
            raise ValueError("Agent output token limit must be positive")


class AgentDelivery(StrEnum):
    HOLD = "HOLD"
    NOTIFY = "NOTIFY"


@dataclass(frozen=True, slots=True)
class AgentFinal:
    content: str
    delivery: AgentDelivery = AgentDelivery.HOLD

    def __post_init__(self) -> None:
        if not self.content.strip():
            raise ValueError("Agent final content is required")


@dataclass(frozen=True, slots=True)
class AgentResponse:
    final: AgentFinal | None = None
    tool_call: AgentToolCall | None = None

    def __post_init__(self) -> None:
        if (self.final is None) == (self.tool_call is None):
            raise ValueError("Agent response must contain exactly one final or tool call")


class AgentModelPort(Protocol):
    async def respond(self, request: AgentRequest) -> AgentResponse: ...


class AgentToolPort(Protocol):
    def definitions(self) -> tuple[AgentToolDefinition, ...]: ...

    async def call(
        self,
        owner_id: str,
        name: str,
        arguments: Mapping[str, object],
        context: ToolCallContext,
    ) -> object: ...


class AgentContextPort(Protocol):
    async def build(
        self,
        user_id: str,
        message: str,
        before: datetime | None = None,
        exclude_id: UUID | None = None,
        conversation_id: UUID | None = None,
        event_case_id: UUID | None = None,
    ) -> str: ...


class AgentRunPort(Protocol):
    async def run(self, owner_id: str, message: str, context: str = "") -> AgentFinal: ...


class AgentRunExecutionPort(Protocol):
    async def get(self, run_id: UUID) -> "AgentRun | None": ...

    async def freeze_effective_delivery(
        self, run_id: UUID, delivery: AgentDelivery
    ) -> AgentDelivery: ...

    async def execute(
        self, run_id: UUID, message: str, context: str = ""
    ) -> "AgentRunExecution": ...


class AgentRunCommandPort(AgentRunExecutionPort, Protocol):
    async def ensure_run(
        self,
        inbox_item_id: UUID,
        user_id: str,
        source_type: str,
        conversation_key: str | None = None,
        event_key: str | None = None,
        occurred_at: datetime | None = None,
    ) -> "AgentRun": ...
