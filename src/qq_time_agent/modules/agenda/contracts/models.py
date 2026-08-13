"""Agenda is the sole authoritative internal schedule contract."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class BusyInterval:
    agenda_entry_id: UUID
    title: str
    starts_at: datetime
    ends_at: datetime
    movable: bool


@dataclass(frozen=True, slots=True)
class AgendaDraft:
    kind: str
    title: str
    starts_at: datetime
    ends_at: datetime
    timezone: str
    source_refs: tuple[str, ...]
    proposal_id: UUID


@dataclass(frozen=True, slots=True)
class AgendaEntryRef:
    agenda_entry_id: UUID
    version: int


@dataclass(frozen=True, slots=True)
class AgendaEntryView:
    agenda_entry_id: UUID
    kind: str
    title: str
    starts_at: datetime
    ends_at: datetime
    timezone: str
    status: str
    source_refs: tuple[str, ...]
    proposal_id: UUID
    version: int


class AgendaQueryPort(Protocol):
    async def get_busy_intervals(
        self, range_start: datetime, range_end: datetime
    ) -> tuple[BusyInterval, ...]: ...

    async def get_entry(self, entry_id: UUID) -> AgendaEntryView | None: ...


class AgendaCommandPort(Protocol):
    async def create_entry(
        self, action_id: UUID, draft: AgendaDraft, idempotency_key: str
    ) -> AgendaEntryRef: ...

    async def revise_entry(
        self,
        action_id: UUID,
        entry_id: UUID,
        expected_version: int,
        draft: AgendaDraft,
        idempotency_key: str,
    ) -> AgendaEntryRef: ...

    async def cancel_entry(
        self, action_id: UUID, entry_id: UUID, expected_version: int, idempotency_key: str
    ) -> AgendaEntryRef: ...

    async def complete_entry(
        self, entry_id: UUID, expected_version: int, idempotency_key: str
    ) -> AgendaEntryRef: ...
