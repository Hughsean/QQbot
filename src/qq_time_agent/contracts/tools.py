"""Provider-neutral tool contracts shared by Agent and tool-owning modules."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    description: str
    input_schema: Mapping[str, object]


class ToolProvider(Protocol):
    def definitions(self) -> tuple[ToolDefinition, ...]: ...

    async def call(self, owner_id: str, name: str, arguments: Mapping[str, object]) -> object: ...


class ToolDispatcher:
    """Combine independently owned allow-listed tool providers without coupling them."""

    def __init__(self, *providers: ToolProvider) -> None:
        definitions = tuple(
            definition for provider in providers for definition in provider.definitions()
        )
        names = [definition.name for definition in definitions]
        if len(names) != len(set(names)):
            raise ValueError("tool names must be unique")
        self._definitions = definitions
        self._providers = {
            definition.name: provider
            for provider in providers
            for definition in provider.definitions()
        }

    def definitions(self) -> tuple[ToolDefinition, ...]:
        return self._definitions

    async def call(self, owner_id: str, name: str, arguments: Mapping[str, object]) -> object:
        provider = self._providers.get(name)
        if provider is None:
            raise ValueError("unknown tool")
        return await provider.call(owner_id, name, arguments)
