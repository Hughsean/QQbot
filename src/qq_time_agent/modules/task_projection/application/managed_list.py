"""Resolve the single owner-managed Microsoft To Do list."""

import unicodedata
from uuid import UUID

from qq_time_agent.contracts.clock import Clock
from qq_time_agent.modules.connections.contracts import TaskConnectionAccessPort
from qq_time_agent.modules.task_projection.application.ports import (
    TaskProjectionTargetRepository,
)
from qq_time_agent.modules.task_projection.contracts import (
    ExternalTaskList,
    ManagedTaskListView,
    TaskProviderPort,
)
from qq_time_agent.modules.task_projection.domain.models import TaskProjectionTarget

MANAGED_LIST_NAME = "小智建议"


class ManagedTaskListNotFoundError(RuntimeError):
    pass


class ManagedTaskListAmbiguousError(RuntimeError):
    pass


class ManagedTaskListOwnershipError(RuntimeError):
    pass


class ManagedTaskListService:
    def __init__(
        self,
        repository: TaskProjectionTargetRepository,
        connections: TaskConnectionAccessPort,
        provider: TaskProviderPort,
        clock: Clock,
    ) -> None:
        self._repository = repository
        self._connections = connections
        self._provider = provider
        self._clock = clock

    async def resolve(self, user_id: str, connection_id: UUID) -> ManagedTaskListView:
        if not user_id.strip():
            raise ValueError("user_id is required")
        access = await self._connections.acquire_task_access(user_id, connection_id)
        lists = await self._provider.list_task_lists(access)
        selected = _select_managed_list(lists)
        current = await self._repository.get_for_connection(connection_id)
        now = self._clock.now()
        if current is None:
            candidate = TaskProjectionTarget.resolve(
                user_id, connection_id, selected.list_ref, selected.display_name, now
            )
            current = await self._repository.add_or_get(candidate)
        elif current.user_id != user_id:
            raise PermissionError("task projection target belongs to another owner")
        elif current.rebind(selected.list_ref, selected.display_name, now):
            await self._repository.save(current, current.version - 1)
        return _view(current)


def _select_managed_list(values: tuple[ExternalTaskList, ...]) -> ExternalTaskList:
    expected = _normalize_name(MANAGED_LIST_NAME)
    matches = tuple(value for value in values if _normalize_name(value.display_name) == expected)
    if not matches:
        raise ManagedTaskListNotFoundError("managed task list was not found")
    if len(matches) != 1:
        raise ManagedTaskListAmbiguousError("managed task list name is ambiguous")
    selected = matches[0]
    if not selected.is_owner or selected.is_shared:
        raise ManagedTaskListOwnershipError("managed task list must be private and owner-managed")
    return selected


def _normalize_name(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip().casefold()


def _view(target: TaskProjectionTarget) -> ManagedTaskListView:
    return ManagedTaskListView(
        target.target_id,
        target.connection_id,
        target.display_name,
        target.status.value,
        target.version,
    )
