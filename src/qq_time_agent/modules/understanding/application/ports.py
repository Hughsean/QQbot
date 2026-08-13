"""Private candidate persistence port."""

from typing import Protocol
from uuid import UUID

from qq_time_agent.modules.understanding.domain.candidates import Candidate


class CandidateRepository(Protocol):
    async def add(self, candidate: Candidate) -> Candidate: ...

    async def get_for_inbox(self, inbox_item_id: UUID) -> Candidate | None: ...

    async def get(self, candidate_id: UUID) -> Candidate | None: ...

    async def list_ids(self, limit: int) -> tuple[UUID, ...]: ...
