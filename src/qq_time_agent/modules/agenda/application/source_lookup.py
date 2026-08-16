"""Narrow Agenda lookup used to match external source identities."""

from typing import Protocol

from qq_time_agent.modules.agenda.contracts import AgendaEntryView
from qq_time_agent.modules.agenda.domain.models import AgendaEntry


class AgendaSourceRepository(Protocol):
    async def find_by_source_ref(self, source_ref: str) -> AgendaEntry | None: ...


class AgendaSourceLookupService:
    def __init__(self, repository: AgendaSourceRepository) -> None:
        self._repository = repository

    async def find_by_source_ref(self, source_ref: str) -> AgendaEntryView | None:
        entry = await self._repository.find_by_source_ref(source_ref)
        if entry is None:
            return None
        return AgendaEntryView(
            entry.agenda_entry_id,
            entry.draft.kind,
            entry.draft.title,
            entry.draft.starts_at,
            entry.draft.ends_at,
            entry.draft.timezone,
            entry.status.value,
            entry.draft.source_refs,
            entry.draft.proposal_id,
            entry.version,
        )
