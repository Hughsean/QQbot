"""Public deterministic normalization contract."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class NormalizedContentView:
    inbox_item_id: UUID
    subject: str
    body: str
    source_hash: str
    normalizer_version: str
    source_ref: str | None = None


class NormalizationPort(Protocol):
    async def normalize(
        self,
        inbox_item_id: UUID,
        subject: str,
        body_text: str,
        body_html: str | None,
        source_hash: str,
        source_ref: str | None = None,
    ) -> NormalizedContentView: ...


class NormalizedContentQueryPort(Protocol):
    async def get(self, inbox_item_id: UUID) -> NormalizedContentView | None: ...
