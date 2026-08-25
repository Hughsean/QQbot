"""Tool port exposed by the independent Calendar System."""

from collections.abc import Mapping
from typing import Protocol

from qq_time_agent.modules.agent.contracts import AgentToolDefinition


class CalendarToolPort(Protocol):
    def definitions(self) -> tuple[AgentToolDefinition, ...]: ...

    async def call(self, owner_id: str, name: str, arguments: Mapping[str, object]) -> object: ...
