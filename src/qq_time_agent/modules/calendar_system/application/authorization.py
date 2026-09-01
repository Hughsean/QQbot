"""Calendar-owned authorization policies for trusted internal principals."""

import secrets
from dataclasses import dataclass

from qq_time_agent.contracts.tools import ToolCallContext

_MUTATIONS = frozenset(
    {"create_agenda", "update_agenda", "complete_agenda", "cancel_agenda", "update_reminder"}
)


@dataclass(frozen=True, slots=True)
class OwnerCalendarAuthorization:
    owner_principal: str

    async def authorize(
        self, principal: str, operation: str, context: ToolCallContext
    ) -> bool:
        return (
            secrets.compare_digest(principal, self.owner_principal)
            and (context.source_type == "QQ_DIRECT" or operation not in _MUTATIONS)
        )
