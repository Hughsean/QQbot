"""Agenda-owned notification snapshots and deterministic conflict detection."""

from datetime import datetime
from uuid import UUID

from qq_time_agent.modules.agenda.application.ports import AgendaRepository
from qq_time_agent.modules.agenda.contracts import AgendaConflictView, AgendaNotificationItem


class AgendaNotificationQueryService:
    def __init__(self, repository: AgendaRepository) -> None:
        self._repository = repository

    async def list_active(
        self, range_start: datetime, range_end: datetime
    ) -> tuple[AgendaNotificationItem, ...]:
        entries = await self._repository.busy_between(range_start, range_end)
        return tuple(
            AgendaNotificationItem(
                value.agenda_entry_id,
                value.version,
                value.draft.title,
                value.draft.starts_at,
                value.draft.ends_at,
                value.draft.kind,
            )
            for value in entries
        )

    async def get_items(self, entry_ids: tuple[UUID, ...]) -> tuple[AgendaNotificationItem, ...]:
        values = []
        for entry_id in entry_ids:
            value = await self._repository.get(entry_id)
            if value is not None and value.status.value == "ACTIVE":
                values.append(
                    AgendaNotificationItem(
                        value.agenda_entry_id,
                        value.version,
                        value.draft.title,
                        value.draft.starts_at,
                        value.draft.ends_at,
                        value.draft.kind,
                    )
                )
        return tuple(values)

    async def list_conflicts(
        self, range_start: datetime, range_end: datetime
    ) -> tuple[AgendaConflictView, ...]:
        entries = await self.list_active(range_start, range_end)
        conflicts: list[AgendaConflictView] = []
        for index, first in enumerate(entries):
            for second in entries[index + 1 :]:
                if second.starts_at >= first.ends_at:
                    break
                if first.starts_at < second.ends_at and second.starts_at < first.ends_at:
                    conflicts.append(AgendaConflictView(first, second))
        return tuple(conflicts)
