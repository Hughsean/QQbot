"""Private candidate persistence port."""

from typing import Protocol
from uuid import UUID

from qq_time_agent.modules.understanding.domain.calendar_changes import CalendarChangeCandidate
from qq_time_agent.modules.understanding.domain.candidates import Candidate


class CalendarChangeRepository(Protocol):
    async def add_version(self, candidate: CalendarChangeCandidate) -> CalendarChangeCandidate: ...


class CalendarEventFingerprinter(Protocol):
    def event_key(self, uid: str, recurrence_id: str | None) -> str: ...

    def version_key(self, event_key: str, sequence: int) -> str: ...


class CandidateRepository(Protocol):
    async def add(self, candidate: Candidate) -> Candidate: ...

    async def get_for_inbox(self, inbox_item_id: UUID) -> Candidate | None: ...

    async def get(self, candidate_id: UUID) -> Candidate | None: ...

    async def list_ids(self, limit: int) -> tuple[UUID, ...]: ...
