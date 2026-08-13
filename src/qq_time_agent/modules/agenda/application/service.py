"""Agenda read model and Actions-only write boundary."""

from datetime import datetime
from uuid import UUID

from qq_time_agent.modules.agenda.application.ports import AgendaRepository
from qq_time_agent.modules.agenda.contracts import (
    AgendaDraft,
    AgendaEntryRef,
    AgendaEntryView,
    BusyInterval,
)
from qq_time_agent.modules.agenda.domain.models import AgendaEntry


class AgendaService:
    def __init__(self, repository: AgendaRepository) -> None:
        self._repository = repository

    async def get_busy_intervals(
        self, range_start: datetime, range_end: datetime
    ) -> tuple[BusyInterval, ...]:
        _validate_range(range_start, range_end)
        values = await self._repository.busy_between(range_start, range_end)
        return tuple(
            BusyInterval(
                value.agenda_entry_id,
                value.draft.title,
                value.draft.starts_at,
                value.draft.ends_at,
                False,
            )
            for value in values
        )

    async def get_entry(self, entry_id: UUID) -> AgendaEntryView | None:
        value = await self._repository.get(entry_id)
        return None if value is None else _view(value)

    async def create_entry(
        self, action_id: UUID, draft: AgendaDraft, idempotency_key: str
    ) -> AgendaEntryRef:
        if not idempotency_key.strip():
            raise ValueError("Agenda idempotency key is required")
        value = await self._repository.create(AgendaEntry.create(action_id, draft), idempotency_key)
        return AgendaEntryRef(value.agenda_entry_id, value.version)

    async def revise_entry(
        self,
        action_id: UUID,
        entry_id: UUID,
        expected_version: int,
        draft: AgendaDraft,
        idempotency_key: str,
    ) -> AgendaEntryRef:
        value = await self._require_entry(entry_id)
        value.revise(action_id, expected_version, draft)
        stored = await self._repository.save(value, expected_version, idempotency_key)
        return AgendaEntryRef(stored.agenda_entry_id, stored.version)

    async def cancel_entry(
        self, action_id: UUID, entry_id: UUID, expected_version: int, idempotency_key: str
    ) -> AgendaEntryRef:
        value = await self._require_entry(entry_id)
        value.cancel(action_id, expected_version)
        stored = await self._repository.save(value, expected_version, idempotency_key)
        return AgendaEntryRef(stored.agenda_entry_id, stored.version)

    async def complete_entry(
        self, entry_id: UUID, expected_version: int, idempotency_key: str
    ) -> AgendaEntryRef:
        value = await self._require_entry(entry_id)
        value.complete(expected_version)
        stored = await self._repository.save(value, expected_version, idempotency_key)
        return AgendaEntryRef(stored.agenda_entry_id, stored.version)

    async def _require_entry(self, entry_id: UUID) -> AgendaEntry:
        value = await self._repository.get(entry_id)
        if value is None:
            raise LookupError("Agenda entry does not exist")
        return value


def _view(value: AgendaEntry) -> AgendaEntryView:
    return AgendaEntryView(
        value.agenda_entry_id,
        value.draft.kind,
        value.draft.title,
        value.draft.starts_at,
        value.draft.ends_at,
        value.draft.timezone,
        value.status.value,
        value.draft.source_refs,
        value.draft.proposal_id,
        value.version,
    )


def _validate_range(start: datetime, end: datetime) -> None:
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("Agenda query range must be timezone-aware")
    if end <= start:
        raise ValueError("Agenda query range must be ordered")
