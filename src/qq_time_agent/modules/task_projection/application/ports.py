"""Task Projection-owned persistence ports."""

from typing import Protocol
from uuid import UUID

from qq_time_agent.modules.task_projection.domain.models import (
    TaskProjectionMapping,
    TaskProjectionTarget,
)


class TaskProjectionTargetRepository(Protocol):
    async def get_for_connection(self, connection_id: UUID) -> TaskProjectionTarget | None: ...

    async def add_or_get(self, target: TaskProjectionTarget) -> TaskProjectionTarget: ...

    async def save(self, target: TaskProjectionTarget, expected_version: int) -> None: ...

    async def list_ready(self, user_id: str) -> tuple[TaskProjectionTarget, ...]: ...


class TaskProjectionMappingRepository(Protocol):
    async def get_for_agenda(
        self, connection_id: UUID, agenda_entry_id: UUID
    ) -> TaskProjectionMapping | None: ...

    async def list_for_agenda(self, agenda_entry_id: UUID) -> tuple[TaskProjectionMapping, ...]: ...

    async def add_or_get(self, mapping: TaskProjectionMapping) -> TaskProjectionMapping: ...

    async def save(self, mapping: TaskProjectionMapping, expected_version: int) -> None: ...
