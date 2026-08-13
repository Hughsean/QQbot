"""Private atomic Knowledge persistence contract."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class IndexedChunk:
    chunk_id: UUID
    ordinal: int
    content: str
    content_hash: str
    embedding: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class IndexedSource:
    source_id: UUID
    source_ref: str
    source_type: str
    source_version: str
    occurred_at: datetime
    trust_level: str
    attributes: dict[str, str]
    chunker_version: str
    index_version: str
    model_id: str
    model_digest: str
    dimensions: int
    chunks: tuple[IndexedChunk, ...]


class KnowledgeRepository(Protocol):
    async def replace_active(self, source: IndexedSource) -> IndexedSource: ...

    async def delete_source(self, source_ref: str) -> int: ...
