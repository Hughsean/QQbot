"""Filtered vector plus lexical retrieval with deterministic weighted RRF."""

import re
from dataclasses import replace

from qq_time_agent.modules.embeddings.contracts import EmbeddingPort
from qq_time_agent.modules.knowledge.contracts import (
    KnowledgeSearchCandidate,
    KnowledgeSearchPort,
    build_index_version,
)
from qq_time_agent.modules.retrieval.contracts import RetrievalFilters, RetrievedChunk

RRF_K = 60
_TOKEN_PATTERN = re.compile(r'"[^"\n]+"|“[^”\n]+”|[\w\u4e00-\u9fff]+', re.UNICODE)


class HybridRetrievalService:
    def __init__(
        self,
        knowledge: KnowledgeSearchPort,
        embeddings: EmbeddingPort,
        model_id: str,
        dimensions: int,
        index_version: str,
        vector_weight: float,
        lexical_weight: float,
        candidate_limit: int,
    ) -> None:
        self._knowledge = knowledge
        self._embeddings = embeddings
        self._model_id = model_id
        self._dimensions = dimensions
        self._index_version = index_version
        self._vector_weight = vector_weight
        self._lexical_weight = lexical_weight
        self._candidate_limit = candidate_limit

    async def retrieve(
        self, query: str, filters: RetrievalFilters, limit: int
    ) -> tuple[RetrievedChunk, ...]:
        _validate(query, filters, limit)
        optimized_query = optimize_query(query)
        batch = await self._embeddings.embed(
            (optimized_query,), self._model_id, self._dimensions
        )
        if batch.model_id != self._model_id or batch.dimensions != self._dimensions:
            raise ValueError("Embedding result does not match active Retrieval index")
        vector = await self._knowledge.search_vector(
            batch.vectors[0],
            build_index_version(
                self._index_version, batch.model_id, batch.model_digest, batch.dimensions
            ),
            batch.model_id,
            batch.model_digest,
            batch.dimensions,
            filters.source_types,
            filters.occurred_after,
            filters.occurred_before,
            self._candidate_limit,
        )
        lexical = await self._knowledge.search_lexical(
            optimized_query,
            build_index_version(
                self._index_version, batch.model_id, batch.model_digest, batch.dimensions
            ),
            filters.source_types,
            filters.occurred_after,
            filters.occurred_before,
            self._candidate_limit,
        )
        return _fuse(vector, lexical, self._vector_weight, self._lexical_weight)[:limit]


def _fuse(
    vector: tuple[KnowledgeSearchCandidate, ...],
    lexical: tuple[KnowledgeSearchCandidate, ...],
    vector_weight: float,
    lexical_weight: float,
) -> tuple[RetrievedChunk, ...]:
    values: dict[object, RetrievedChunk] = {}
    for weight, ranked in ((vector_weight, vector), (lexical_weight, lexical)):
        for rank, candidate in enumerate(ranked, start=1):
            existing = values.get(candidate.chunk_id)
            base = _result(candidate) if existing is None else existing
            values[candidate.chunk_id] = replace(
                base,
                vector_distance=(
                    candidate.vector_distance
                    if candidate.vector_distance is not None
                    else base.vector_distance
                ),
                lexical_score=(
                    candidate.lexical_score
                    if candidate.lexical_score is not None
                    else base.lexical_score
                ),
                fusion_score=base.fusion_score + weight / (RRF_K + rank),
            )
    return tuple(
        sorted(
            values.values(),
            key=lambda item: (
                -item.fusion_score,
                -item.occurred_at.timestamp(),
                str(item.chunk_id),
            ),
        )
    )


def optimize_query(query: str, max_chars: int = 6000) -> str:
    """Normalize whitespace and remove repeated lexical terms deterministically."""
    if max_chars < 1:
        raise ValueError("query maximum length must be positive")
    value = " ".join(query.strip().split())
    if not value:
        return ""
    terms: list[str] = []
    seen: set[str] = set()
    for term in _TOKEN_PATTERN.findall(value):
        key = term.casefold()
        if key in seen:
            continue
        seen.add(key)
        terms.append(term)
    optimized = " ".join(terms)
    return optimized[:max_chars]


def _result(value: KnowledgeSearchCandidate) -> RetrievedChunk:
    return RetrievedChunk(
        value.chunk_id,
        value.source_ref,
        value.source_type,
        value.source_version,
        value.occurred_at,
        value.content,
        value.vector_distance,
        value.lexical_score,
        0.0,
    )


def _validate(query: str, filters: RetrievalFilters, limit: int) -> None:
    if not query.strip():
        raise ValueError("Retrieval query is required")
    if limit < 1 or limit > 30:
        raise ValueError("Retrieval limit must be between 1 and 30")
    for value in (filters.occurred_after, filters.occurred_before):
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("Retrieval time filters must be timezone-aware")
