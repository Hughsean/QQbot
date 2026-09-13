"""Task projection application use cases."""

from qq_time_agent.modules.task_projection.application.completion import (
    ReminderCompletionGate,
    TaskCompletionCoordinator,
)
from qq_time_agent.modules.task_projection.application.completion_sync import (
    TaskCompletionSyncError,
    TaskCompletionSyncService,
)
from qq_time_agent.modules.task_projection.application.managed_list import (
    MANAGED_LIST_NAME,
    ManagedTaskListAmbiguousError,
    ManagedTaskListNotFoundError,
    ManagedTaskListOwnershipError,
    ManagedTaskListService,
)
from qq_time_agent.modules.task_projection.application.projection import (
    ProjectionOperationError,
    TaskProjectionService,
)

__all__ = [
    "MANAGED_LIST_NAME",
    "ManagedTaskListAmbiguousError",
    "ManagedTaskListNotFoundError",
    "ManagedTaskListOwnershipError",
    "ManagedTaskListService",
    "ProjectionOperationError",
    "ReminderCompletionGate",
    "TaskCompletionCoordinator",
    "TaskCompletionSyncError",
    "TaskCompletionSyncService",
    "TaskProjectionService",
]
