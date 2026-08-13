"""Private Agenda persistence port."""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from qq_time_agent.modules.agenda.domain.models import AgendaEntry


class AgendaRepository(Protocol):
    async def create(self, entry: AgendaEntry, idempotency_key: str) -> AgendaEntry: ...

    async def get(self, entry_id: UUID) -> AgendaEntry | None: ...

    async def busy_between(
        self, range_start: datetime, range_end: datetime
    ) -> tuple[AgendaEntry, ...]: ...

    async def save(
        self, entry: AgendaEntry, expected_version: int, idempotency_key: str
    ) -> AgendaEntry: ...
