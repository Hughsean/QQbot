"""Task Projection-owned persistence ports."""

from typing import Protocol
from uuid import UUID

from qq_time_agent.modules.task_projection.domain.models import TaskProjectionTarget


class TaskProjectionTargetRepository(Protocol):
    async def get_for_connection(self, connection_id: UUID) -> TaskProjectionTarget | None: ...

    async def add_or_get(self, target: TaskProjectionTarget) -> TaskProjectionTarget: ...

    async def save(self, target: TaskProjectionTarget, expected_version: int) -> None: ...
