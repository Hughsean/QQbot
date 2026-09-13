"""Stable provider-neutral task projection contracts."""

from dataclasses import dataclass
from datetime import datetime
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


@dataclass(frozen=True, slots=True)
class ExternalTaskDraft:
    stable_marker: str
    title: str
    starts_at: datetime
    ends_at: datetime
    timezone: str

    def __post_init__(self) -> None:
        if not self.stable_marker.strip() or not self.title.strip() or not self.timezone.strip():
            raise ValueError("external task draft identity is required")
        if self.starts_at.tzinfo is None or self.ends_at.tzinfo is None:
            raise ValueError("external task draft times must be timezone-aware")
        if self.ends_at <= self.starts_at:
            raise ValueError("external task draft time range is invalid")


@dataclass(frozen=True, slots=True)
class ExternalTaskView:
    task_ref: str
    revision: str | None
    completed: bool


@dataclass(frozen=True, slots=True)
class ProjectionResult:
    agenda_entry_id: UUID
    agenda_entry_version: int
    outcome: str
    projected_targets: int


class TaskProviderPort(Protocol):
    async def list_task_lists(
        self, access_grant: TaskAccessGrant
    ) -> tuple[ExternalTaskList, ...]: ...

    async def upsert_task(
        self,
        access_grant: TaskAccessGrant,
        list_ref: str,
        draft: ExternalTaskDraft,
        task_ref: str | None,
    ) -> ExternalTaskView: ...

    async def find_task(
        self,
        access_grant: TaskAccessGrant,
        list_ref: str,
        stable_marker: str,
    ) -> ExternalTaskView | None: ...

    async def close_task(
        self,
        access_grant: TaskAccessGrant,
        list_ref: str,
        task_ref: str,
        completed: bool,
    ) -> None: ...


class ManagedTaskListSetupPort(Protocol):
    async def resolve(self, user_id: str, connection_id: UUID) -> ManagedTaskListView: ...


class TaskProjectionCommandPort(Protocol):
    async def project_agenda_entry(
        self, entry_id: UUID, expected_version: int, idempotency_key: str
    ) -> ProjectionResult: ...
