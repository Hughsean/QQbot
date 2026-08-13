"""Authoritative versioned Agenda entry."""

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from qq_time_agent.modules.agenda.contracts import AgendaDraft


class AgendaKind(StrEnum):
    EVENT = "EVENT"
    TASK_BLOCK = "TASK_BLOCK"


class AgendaStatus(StrEnum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


@dataclass(slots=True)
class AgendaEntry:
    agenda_entry_id: UUID
    action_id: UUID
    draft: AgendaDraft
    status: AgendaStatus = AgendaStatus.ACTIVE
    version: int = 1

    @classmethod
    def create(cls, action_id: UUID, draft: AgendaDraft) -> "AgendaEntry":
        _validate_draft(draft)
        return cls(uuid4(), action_id, draft)

    def revise(self, action_id: UUID, expected_version: int, draft: AgendaDraft) -> None:
        self._require_active(expected_version)
        _validate_draft(draft)
        self.action_id = action_id
        self.draft = draft
        self.version += 1

    def cancel(self, action_id: UUID, expected_version: int) -> None:
        self._require_active(expected_version)
        self.action_id = action_id
        self.status = AgendaStatus.CANCELLED
        self.version += 1

    def complete(self, expected_version: int) -> None:
        self._require_active(expected_version)
        self.status = AgendaStatus.COMPLETED
        self.version += 1

    def _require_active(self, expected_version: int) -> None:
        if self.version != expected_version:
            raise ValueError("Agenda entry version is stale")
        if self.status is not AgendaStatus.ACTIVE:
            raise ValueError("Agenda entry is not active")


def _validate_draft(value: AgendaDraft) -> None:
    try:
        AgendaKind(value.kind)
        ZoneInfo(value.timezone)
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise ValueError("Agenda kind or timezone is invalid") from exc
    if not value.title.strip() or not value.source_refs:
        raise ValueError("Agenda title and source references are required")
    for moment in (value.starts_at, value.ends_at):
        if moment.tzinfo is None or moment.utcoffset() is None:
            raise ValueError("Agenda times must be timezone-aware")
    if value.ends_at <= value.starts_at:
        raise ValueError("Agenda end must follow start")
