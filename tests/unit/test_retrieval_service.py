from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from qq_time_agent.modules.embeddings.contracts import EmbeddingBatch, EmbeddingProviderHealth
from qq_time_agent.modules.knowledge.contracts import KnowledgeSearchCandidate
from qq_time_agent.modules.retrieval.application.service import (
    HybridRetrievalService,
    optimize_query,
)
from qq_time_agent.modules.retrieval.contracts import RetrievalFilters


@dataclass
class Embeddings:
    async def embed(self, texts: tuple[str, ...], model_id: str, dimensions: int) -> EmbeddingBatch:
        return EmbeddingBatch(model_id, "digest", dimensions, ((1.0, 0.0),))

    async def health(self) -> EmbeddingProviderHealth:
        return EmbeddingProviderHealth(True, "model", 2, "digest")


@dataclass
class Knowledge:
    vector: tuple[KnowledgeSearchCandidate, ...]
    lexical: tuple[KnowledgeSearchCandidate, ...]

    async def search_vector(
        self, *args: object, **kwargs: object
    ) -> tuple[KnowledgeSearchCandidate, ...]:
        return self.vector

    async def search_lexical(
        self, *args: object, **kwargs: object
    ) -> tuple[KnowledgeSearchCandidate, ...]:
        return self.lexical


def _candidate(name: str, vector: float | None, lexical: float | None) -> KnowledgeSearchCandidate:
    return KnowledgeSearchCandidate(
        uuid4(),
        f"mail:{name}",
        "MICROSOFT_MAIL",
        "v1",
        datetime(2026, 8, 20, tzinfo=UTC),
        name,
        0,
        vector,
        lexical,
    )


def test_query_optimization_removes_duplicate_terms_and_bounds_length() -> None:
    assert optimize_query('  星河   报价 星河 "截止 周五"  ') == '星河 报价 "截止 周五"'
    assert len(optimize_query("x" * 100, 20)) <= 20


@pytest.mark.asyncio
async def test_hybrid_rrf_fuses_deduplicates_and_preserves_sources() -> None:
    shared = _candidate("项目星河", 0.1, None)
    lexical_shared = KnowledgeSearchCandidate(
        shared.chunk_id,
        shared.source_ref,
        shared.source_type,
        shared.source_version,
        shared.occurred_at,
        shared.content,
        shared.ordinal,
        None,
        0.9,
    )
    lexical_only = _candidate("报价截止", None, 0.8)
    service = HybridRetrievalService(
        Knowledge((shared,), (lexical_shared, lexical_only)),
        Embeddings(),
        "model",
        2,
        "index-v1",
        0.65,
        0.35,
        10,
    )
    result = await service.retrieve("星河报价", RetrievalFilters(), 10)
    assert result[0].chunk_id == shared.chunk_id
    assert result[0].vector_distance == 0.1 and result[0].lexical_score == 0.9
    assert result[0].source_ref == "mail:项目星河"


@pytest.mark.asyncio
async def test_retrieval_validates_query_limit_and_aware_filters() -> None:
    service = HybridRetrievalService(
        Knowledge((), ()), Embeddings(), "model", 2, "v1", 0.5, 0.5, 10
    )
    with pytest.raises(ValueError, match="query"):
        await service.retrieve(" ", RetrievalFilters(), 10)
    with pytest.raises(ValueError, match="between"):
        await service.retrieve("q", RetrievalFilters(), 31)
    with pytest.raises(ValueError, match="timezone-aware"):
        await service.retrieve("q", RetrievalFilters(occurred_after=datetime(2026, 8, 20)), 10)
