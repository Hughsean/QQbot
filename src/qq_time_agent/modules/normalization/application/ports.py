"""Private Normalization persistence port."""

from typing import Protocol
from uuid import UUID

from qq_time_agent.modules.normalization.contracts import NormalizedContentView


class NormalizedContentRepository(Protocol):
    async def upsert(
        self,
        inbox_item_id: UUID,
        subject: str,
        body: str,
        source_hash: str,
        normalizer_version: str,
        source_ref: str | None,
    ) -> NormalizedContentView: ...

    async def get(self, inbox_item_id: UUID) -> NormalizedContentView | None: ...
