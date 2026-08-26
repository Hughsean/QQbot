"""Tool port exposed by the independent Calendar System."""

from collections.abc import Mapping
from typing import Protocol

from qq_time_agent.contracts.tools import ToolDefinition


class CalendarAuthorizationPort(Protocol):
    async def authorize(self, principal: str, operation: str) -> bool: ...


class CalendarToolPort(Protocol):
    def definitions(self) -> tuple[ToolDefinition, ...]: ...

    async def call(self, owner_id: str, name: str, arguments: Mapping[str, object]) -> object: ...
