"""Inbox-owned enumeration for connection-wide source deletion."""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from qq_time_agent.contracts.clock import Clock
from qq_time_agent.modules.data_lifecycle.contracts import DeletionRequestPort


class ConnectionInboxDeletionRepository(Protocol):
    async def allow_connection(self, connection_id: UUID, now: datetime) -> None: ...

    async def block_connection(self, connection_id: UUID, now: datetime) -> None: ...

    async def mark_connection_deleted(self, connection_id: UUID, now: datetime) -> int: ...

    async def list_source_refs_for_connection(
        self, connection_id: UUID, after_id: UUID | None, limit: int
    ) -> tuple[tuple[UUID, str], ...]: ...

    async def delete_cursor(self, connection_id: UUID) -> None: ...


class ConnectionSourceDeletionService:
    def __init__(
        self,
        repository: ConnectionInboxDeletionRepository,
        deletion: DeletionRequestPort,
        clock: Clock,
        batch_size: int = 100,
    ) -> None:
        if batch_size < 1 or batch_size > 100:
            raise ValueError("source deletion batch must be between 1 and 100")
        self._repository = repository
        self._deletion = deletion
        self._clock = clock
        self._batch_size = batch_size

    async def delete_connection_sources(self, connection_id: UUID) -> int:
        await self.block_connection_sources(connection_id)
        await self._repository.mark_connection_deleted(connection_id, self._clock.now())
        count = 0
        after_id: UUID | None = None
        while True:
            batch = await self._repository.list_source_refs_for_connection(
                connection_id, after_id, self._batch_size
            )
            if not batch:
                break
            for inbox_item_id, source_ref in batch:
                await self._record_once(source_ref)
                after_id = inbox_item_id
                count += 1
            if len(batch) < self._batch_size:
                break
        await self._repository.delete_cursor(connection_id)
        return count

    async def allow_connection_sources(self, connection_id: UUID) -> None:
        await self._repository.allow_connection(connection_id, self._clock.now())

    async def block_connection_sources(self, connection_id: UUID) -> None:
        await self._repository.block_connection(connection_id, self._clock.now())

    async def _record_once(self, source_ref: str) -> None:
        try:
            await self._deletion.record_deletion(source_ref)
        except Exception:
            await self._deletion.record_deletion(source_ref)
