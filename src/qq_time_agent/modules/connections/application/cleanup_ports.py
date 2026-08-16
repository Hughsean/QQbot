"""Application ports for connection-scoped asynchronous cleanup."""

from datetime import datetime
from typing import Protocol
from uuid import UUID


class ConnectionJobCancellationPort(Protocol):
    async def cancel_pending_for_connection(
        self, connection_id: UUID, cancelled_at: datetime
    ) -> int: ...


class ConnectionSourceDeletionPort(Protocol):
    async def delete_connection_sources(self, connection_id: UUID) -> int: ...

    async def allow_connection_sources(self, connection_id: UUID) -> None: ...

    async def block_connection_sources(self, connection_id: UUID) -> None: ...
