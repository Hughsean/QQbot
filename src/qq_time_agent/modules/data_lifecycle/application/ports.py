"""Internal persistence ports for the Data Lifecycle module."""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from qq_time_agent.modules.data_lifecycle.domain.models import Tombstone


class TombstoneRepository(Protocol):
    async def add(self, tombstone: Tombstone) -> Tombstone: ...

    async def find_due(self, now: datetime, limit: int) -> list[Tombstone]: ...

    async def find_for_replay(self, limit: int) -> list[Tombstone]: ...

    async def record_module_purge(
        self, tombstone_id: UUID, module_name: str, deleted_count: int
    ) -> None: ...

    async def mark_complete(self, tombstone_id: UUID) -> None: ...
