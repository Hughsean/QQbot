"""Public deletion contracts implemented independently by data-owning modules."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class TombstoneRef:
    tombstone_id: UUID
    subject_ref: str
    purge_by: datetime


class DeletionRequestPort(Protocol):
    async def record_deletion(self, subject_ref: str) -> TombstoneRef: ...


@dataclass(frozen=True, slots=True)
class PurgeResult:
    module_name: str
    deleted_count: int
    already_absent: bool = False


class PurgePort(Protocol):
    module_name: str

    async def purge_subject(self, subject_ref: str, tombstone_id: UUID) -> PurgeResult:
        """Idempotently remove or make the subject unavailable in the owning module."""


class ExpiryPort(Protocol):
    module_name: str

    async def purge_expired(self, cutoff: datetime, limit: int) -> PurgeResult: ...


class ExpiredSourcePort(Protocol):
    async def find_expired(self, cutoff: datetime, limit: int) -> tuple[str, ...]: ...
