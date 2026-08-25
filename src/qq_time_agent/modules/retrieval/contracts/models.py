"""Traceable hybrid retrieval result contract."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class RetrievalFilters:
    source_types: tuple[str, ...] = ()
    occurred_after: datetime | None = None
    occurred_before: datetime | None = None


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    chunk_id: UUID
    source_ref: str
    source_type: str
    source_version: str
    occurred_at: datetime
    content: str
    vector_distance: float | None
    lexical_score: float | None
    fusion_score: float


class RetrievalPort(Protocol):
    async def retrieve(
        self, query: str, filters: RetrievalFilters, limit: int
    ) -> tuple[RetrievedChunk, ...]: ...


class RagToolsPort(Protocol):
    async def call(self, name: str, owner_id: str, arguments: dict[str, object]) -> object: ...
