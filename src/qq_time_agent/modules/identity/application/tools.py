"""Identity-owned Agent tool for owner group-chat aliases."""

from collections.abc import Mapping

from qq_time_agent.contracts.tools import ToolDefinition
from qq_time_agent.modules.identity.contracts import OwnerGroupAliasCommandPort

_TOOL_NAME = "register_owner_group_alias"


class OwnerGroupAliasToolRegistry:
    def __init__(self, aliases: OwnerGroupAliasCommandPort) -> None:
        self._aliases = aliases
        self._definitions = (
            ToolDefinition(
                _TOOL_NAME,
                "Register an owner-declared display name for forwarded group-chat attribution.",
                {
                    "type": "object",
                    "properties": {"alias": {"type": "string"}},
                    "required": ["alias"],
                },
            ),
        )

    def definitions(self) -> tuple[ToolDefinition, ...]:
        return self._definitions

    async def call(self, owner_id: str, name: str, arguments: Mapping[str, object]) -> object:
        if name != _TOOL_NAME or set(arguments) != {"alias"}:
            raise ValueError("identity tool request is invalid")
        alias = arguments.get("alias")
        if not isinstance(alias, str):
            raise ValueError("alias is required")
        result = await self._aliases.register_owner_group_alias(owner_id, alias)
        return {"alias": result.alias, "status": "REGISTERED"}
