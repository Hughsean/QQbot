"""Public task projection contracts."""

from qq_time_agent.modules.task_projection.contracts.models import (
    ExternalTaskChange,
    ExternalTaskDeltaPage,
    ExternalTaskDraft,
    ExternalTaskList,
    ExternalTaskView,
    ManagedTaskListSetupPort,
    ManagedTaskListView,
    ProjectionResult,
    ReminderCompletionDecision,
    ReminderCompletionGatePort,
    ReminderCompletionOutcome,
    TaskCompletionSyncPort,
    TaskProjectionCommandPort,
    TaskProviderError,
    TaskProviderPort,
)

__all__ = [
    "ExternalTaskChange",
    "ExternalTaskDeltaPage",
    "ExternalTaskDraft",
    "ExternalTaskList",
    "ExternalTaskView",
    "ManagedTaskListSetupPort",
    "ManagedTaskListView",
    "ProjectionResult",
    "ReminderCompletionDecision",
    "ReminderCompletionGatePort",
    "ReminderCompletionOutcome",
    "TaskCompletionSyncPort",
    "TaskProjectionCommandPort",
    "TaskProviderError",
    "TaskProviderPort",
]
