from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

import pytest

from qq_time_agent.modules.data_lifecycle.contracts import DeletionRequestPort
from qq_time_agent.modules.inbox.application.connection_deletion import (
    ConnectionInboxDeletionRepository,
    ConnectionSourceDeletionService,
)


@dataclass
class Repository:
    rows: list[tuple[UUID, str]]
    cursor_deleted: bool = False

    async def allow_connection(self, connection_id: UUID, now: datetime) -> None:
        return None

    async def block_connection(self, connection_id: UUID, now: datetime) -> None:
        return None

    async def mark_connection_deleted(self, connection_id: UUID, now: datetime) -> int:
        assert now.tzinfo is not None
        return len(self.rows)

    async def list_source_refs_for_connection(
        self, connection_id: UUID, after_id: UUID | None, limit: int
    ) -> tuple[tuple[UUID, str], ...]:
        values = sorted(self.rows)
        if after_id is not None:
            values = [row for row in values if row[0] > after_id]
        return tuple(values[:limit])

    async def delete_cursor(self, connection_id: UUID) -> None:
        self.cursor_deleted = True


@dataclass
class Deletion:
    values: list[str] = field(default_factory=list)

    async def record_deletion(self, subject_ref: str) -> object:
        self.values.append(subject_ref)
        return object()


class Clock:
    def now(self) -> datetime:
        return datetime(2026, 8, 13, tzinfo=UTC)


@pytest.mark.asyncio
async def test_connection_sources_are_paged_into_tombstones_and_cursor_removed() -> None:
    rows = sorted((uuid4(), f"qq-mail:source-{index}") for index in range(3))
    repository = Repository(rows)
    deletion = Deletion()
    service = ConnectionSourceDeletionService(
        cast(ConnectionInboxDeletionRepository, repository),
        cast(DeletionRequestPort, deletion),
        Clock(),
        batch_size=2,
    )

    assert await service.delete_connection_sources(uuid4()) == 3
    assert deletion.values == [row[1] for row in rows]
    assert repository.cursor_deleted
