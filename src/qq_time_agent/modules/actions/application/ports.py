"""Private Action persistence port."""

from typing import Protocol
from uuid import UUID

from qq_time_agent.modules.actions.domain.models import ActionRequest


class ActionRepository(Protocol):
    async def add(self, action: ActionRequest) -> ActionRequest: ...

    async def get(self, action_id: UUID) -> ActionRequest | None: ...

    async def save(self, action: ActionRequest) -> None: ...
