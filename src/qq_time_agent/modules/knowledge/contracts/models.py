"""Stable source indexing and read-only candidate contracts."""

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID


def build_index_version(
    base: str,
    model_id: str,
    model_digest: str,
    dimensions: int,
    normalizer_version: str = "mail-text-v1",
    chunker_version: str = "deterministic-v1",
) -> str:
    values = (base, model_id, model_digest, normalizer_version, chunker_version)
    if any(not value.strip() for value in values) or dimensions < 1:
        raise ValueError("Knowledge index version contract is incomplete")
    contract = "|".join((*values, str(dimensions)))
    return f"{base}:{hashlib.sha256(contract.encode()).hexdigest()[:16]}"


@dataclass(frozen=True, slots=True)
class SourceMetadata:
    source_type: str
    occurred_at: datetime
    trust_level: str
    attributes: dict[str, str]


@dataclass(frozen=True, slots=True)
class IndexResult:
    source_id: UUID
    source_ref: str
    source_version: str
    chunks_indexed: int
    index_version: str


@dataclass(frozen=True, slots=True)
class KnowledgeSearchCandidate:
    chunk_id: UUID
    source_ref: str
    source_type: str
    source_version: str
    occurred_at: datetime
    content: str
    ordinal: int
    vector_distance: float | None
    lexical_score: float | None


class KnowledgeIndexPort(Protocol):
    async def upsert_source(
        self,
        source_ref: str,
        source_version: str,
        normalized_content: str,
        metadata: SourceMetadata,
    ) -> IndexResult: ...

    async def delete_source(self, source_ref: str) -> int: ...


class KnowledgeSearchPort(Protocol):
    async def search_vector(
        self,
        vector: tuple[float, ...],
        index_version: str,
        model_id: str,
        model_digest: str,
        dimensions: int,
        source_types: tuple[str, ...],
        occurred_after: datetime | None,
        occurred_before: datetime | None,
        limit: int,
    ) -> tuple[KnowledgeSearchCandidate, ...]: ...

    async def search_lexical(
        self,
        query: str,
        index_version: str,
        source_types: tuple[str, ...],
        occurred_after: datetime | None,
        occurred_before: datetime | None,
        limit: int,
    ) -> tuple[KnowledgeSearchCandidate, ...]: ...
