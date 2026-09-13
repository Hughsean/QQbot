"""Stable provider-neutral task projection contracts."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from qq_time_agent.modules.connections.contracts import TaskAccessGrant


class TaskProviderError(RuntimeError):
    def __init__(self, failure_class: str) -> None:
        super().__init__(failure_class)
        self.failure_class = failure_class


@dataclass(frozen=True, slots=True)
class ExternalTaskList:
    list_ref: str
    display_name: str
    is_owner: bool
    is_shared: bool
    well_known_name: str

    def __post_init__(self) -> None:
        if not self.list_ref.strip() or not self.display_name.strip():
            raise ValueError("external task list identity is required")
        if len(self.list_ref) > 1024 or len(self.display_name) > 120:
            raise ValueError("external task list identity is too long")


@dataclass(frozen=True, slots=True)
class ManagedTaskListView:
    target_id: UUID
    connection_id: UUID
    display_name: str
    status: str
    version: int


class TaskProviderPort(Protocol):
    async def list_task_lists(
        self, access_grant: TaskAccessGrant
    ) -> tuple[ExternalTaskList, ...]: ...


class ManagedTaskListSetupPort(Protocol):
    async def resolve(self, user_id: str, connection_id: UUID) -> ManagedTaskListView: ...
