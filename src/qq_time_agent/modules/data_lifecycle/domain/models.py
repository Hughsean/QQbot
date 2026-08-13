"""Pure domain state for replayable deletion records."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4


class TombstoneStatus(StrEnum):
    PENDING = "PENDING"
    COMPLETE = "COMPLETE"


@dataclass(slots=True)
class Tombstone:
    tombstone_id: UUID
    subject_ref: str
    requested_at: datetime
    purge_by: datetime
    status: TombstoneStatus = TombstoneStatus.PENDING
    completed_modules: set[str] = field(default_factory=set)

    @classmethod
    def request(cls, subject_ref: str, requested_at: datetime, purge_by: datetime) -> "Tombstone":
        _require_aware(requested_at)
        _require_aware(purge_by)
        if not subject_ref.strip():
            raise ValueError("subject_ref is required")
        if purge_by < requested_at:
            raise ValueError("purge_by cannot precede requested_at")
        return cls(uuid4(), subject_ref, requested_at, purge_by)

    def record_module_purge(self, module_name: str) -> None:
        if self.status is TombstoneStatus.COMPLETE:
            return
        if not module_name.strip():
            raise ValueError("module_name is required")
        self.completed_modules.add(module_name)

    def complete(self, required_modules: set[str]) -> None:
        if not required_modules.issubset(self.completed_modules):
            raise ValueError("all module purges must succeed before completion")
        self.status = TombstoneStatus.COMPLETE


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timezone-aware datetime required")
