"""Pure state for external task targets and Agenda projections."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4


class TaskProjectionProvider(StrEnum):
    MICROSOFT_TODO = "MICROSOFT_TODO"


class TaskProjectionTargetStatus(StrEnum):
    READY = "READY"
    UNAVAILABLE = "UNAVAILABLE"


class TaskProjectionStatus(StrEnum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    RETRY_WAIT = "RETRY_WAIT"
    DETACHED = "DETACHED"
    CLOSED = "CLOSED"
    FAILED_FINAL = "FAILED_FINAL"


@dataclass(slots=True)
class TaskProjectionTarget:
    target_id: UUID
    user_id: str
    connection_id: UUID
    provider: TaskProjectionProvider
    provider_list_ref: str
    display_name: str
    status: TaskProjectionTargetStatus
    resolved_at: datetime
    updated_at: datetime
    version: int = 1

    @classmethod
    def resolve(
        cls,
        user_id: str,
        connection_id: UUID,
        provider_list_ref: str,
        display_name: str,
        now: datetime,
    ) -> "TaskProjectionTarget":
        _identity(user_id, provider_list_ref, display_name)
        _aware(now)
        return cls(
            uuid4(),
            user_id,
            connection_id,
            TaskProjectionProvider.MICROSOFT_TODO,
            provider_list_ref,
            display_name,
            TaskProjectionTargetStatus.READY,
            now,
            now,
        )

    def rebind(self, provider_list_ref: str, display_name: str, now: datetime) -> bool:
        _identity(self.user_id, provider_list_ref, display_name)
        _aware(now)
        if (
            self.provider_list_ref == provider_list_ref
            and self.display_name == display_name
            and self.status is TaskProjectionTargetStatus.READY
        ):
            return False
        self.provider_list_ref = provider_list_ref
        self.display_name = display_name
        self.status = TaskProjectionTargetStatus.READY
        self.resolved_at = now
        self.updated_at = now
        self.version += 1
        return True


@dataclass(slots=True)
class TaskProjectionMapping:
    mapping_id: UUID
    user_id: str
    agenda_entry_id: UUID
    agenda_entry_version: int
    connection_id: UUID
    provider: TaskProjectionProvider
    provider_list_ref: str
    provider_task_ref: str | None
    status: TaskProjectionStatus
    provider_revision: str | None
    last_projected_at: datetime | None
    last_checked_at: datetime | None
    last_observed_completion: bool | None
    version: int = 1

    @classmethod
    def pending(
        cls,
        user_id: str,
        agenda_entry_id: UUID,
        agenda_entry_version: int,
        connection_id: UUID,
        provider_list_ref: str,
    ) -> "TaskProjectionMapping":
        if not user_id.strip() or not provider_list_ref.strip() or agenda_entry_version < 1:
            raise ValueError("task projection mapping identity is invalid")
        return cls(
            uuid4(),
            user_id,
            agenda_entry_id,
            agenda_entry_version,
            connection_id,
            TaskProjectionProvider.MICROSOFT_TODO,
            provider_list_ref,
            None,
            TaskProjectionStatus.PENDING,
            None,
            None,
            None,
            None,
        )

    def activate(
        self,
        agenda_entry_version: int,
        provider_task_ref: str,
        provider_revision: str | None,
        projected_at: datetime,
    ) -> None:
        if not provider_task_ref.strip() or agenda_entry_version < 1:
            raise ValueError("provider task reference and Agenda version are required")
        _aware(projected_at)
        self.agenda_entry_version = agenda_entry_version
        self.provider_task_ref = provider_task_ref
        self.provider_revision = provider_revision
        self.last_projected_at = projected_at
        self.status = TaskProjectionStatus.ACTIVE
        self.version += 1

    def mark_retry(self, agenda_entry_version: int) -> None:
        if agenda_entry_version < 1:
            raise ValueError("Agenda version is required")
        self.agenda_entry_version = agenda_entry_version
        self.status = TaskProjectionStatus.RETRY_WAIT
        self.version += 1

    def retarget(self, provider_list_ref: str, agenda_entry_version: int) -> None:
        if not provider_list_ref.strip() or agenda_entry_version < 1:
            raise ValueError("projection target and Agenda version are required")
        self.provider_list_ref = provider_list_ref
        self.provider_task_ref = None
        self.provider_revision = None
        self.agenda_entry_version = agenda_entry_version
        self.status = TaskProjectionStatus.PENDING
        self.version += 1

    def detach(self) -> None:
        if self.status in {TaskProjectionStatus.CLOSED, TaskProjectionStatus.FAILED_FINAL}:
            raise ValueError("terminal task projection cannot detach")
        self.status = TaskProjectionStatus.DETACHED
        self.version += 1

    def close(self, agenda_entry_version: int, projected_at: datetime) -> None:
        if agenda_entry_version < 1:
            raise ValueError("Agenda version is required")
        _aware(projected_at)
        if self.status is not TaskProjectionStatus.CLOSED:
            self.agenda_entry_version = agenda_entry_version
            self.last_projected_at = projected_at
            self.status = TaskProjectionStatus.CLOSED
            self.version += 1


def _identity(user_id: str, provider_list_ref: str, display_name: str) -> None:
    if not user_id.strip() or not provider_list_ref.strip() or not display_name.strip():
        raise ValueError("task projection target identity is required")
    if len(user_id) > 120 or len(provider_list_ref) > 1024 or len(display_name) > 120:
        raise ValueError("task projection target identity is too long")


def _aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("task projection time must be timezone-aware")
