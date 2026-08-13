from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from qq_time_agent.modules.ai_gateway.application.rag_answer import RetrievalAnswerService
from qq_time_agent.modules.ai_gateway.contracts import StructuredRequest, StructuredResponse
from qq_time_agent.modules.retrieval.contracts import RetrievalFilters, RetrievedChunk

NOW = datetime(2026, 8, 20, tzinfo=UTC)


@dataclass
class Retrieval:
    chunks: tuple[RetrievedChunk, ...]

    async def retrieve(
        self, query: str, filters: RetrievalFilters, limit: int
    ) -> tuple[RetrievedChunk, ...]:
        return self.chunks


@dataclass
class Model:
    output: dict[str, object]
    request: StructuredRequest | None = None

    async def invoke(self, request: StructuredRequest) -> StructuredResponse:
        self.request = request
        return StructuredResponse(self.output, "model", 10, 5)


def _chunk(source_ref: str = "mail:1") -> RetrievedChunk:
    return RetrievedChunk(
        uuid4(), source_ref, "MICROSOFT_MAIL", "v1", NOW, "报价截止周五", 0.1, 0.8, 0.02
    )


@pytest.mark.asyncio
async def test_answer_only_accepts_citations_from_retrieved_evidence() -> None:
    model = Model({"answer": "报价周五截止。", "citations": ["S1"], "insufficient_evidence": False})
    result = await RetrievalAnswerService(Retrieval((_chunk(),)), model, 10).answer("何时截止")
    assert result.answer == "报价周五截止。"
    assert result.citations[0].source_ref == "mail:1"
    assert model.request is not None and "不得修改日程" in model.request.system_instruction


@pytest.mark.asyncio
async def test_answer_rejects_hallucinated_or_missing_citation() -> None:
    model = Model({"answer": "错误回答", "citations": ["S9"], "insufficient_evidence": False})
    with pytest.raises(ValueError, match="outside retrieval"):
        await RetrievalAnswerService(Retrieval((_chunk(),)), model, 10).answer("问题")
    model.output = {"answer": "无引用", "citations": [], "insufficient_evidence": False}
    with pytest.raises(ValueError, match="must cite"):
        await RetrievalAnswerService(Retrieval((_chunk(),)), model, 10).answer("问题")


@pytest.mark.asyncio
async def test_answer_returns_safe_unknown_without_model_when_no_evidence() -> None:
    model = Model({})
    result = await RetrievalAnswerService(Retrieval(()), model, 10).answer("未知问题")
    assert result.insufficient_evidence and result.citations == ()
    assert model.request is None


def test_answer_service_rejects_invalid_limits() -> None:
    with pytest.raises(ValueError, match="limits"):
        RetrievalAnswerService(Retrieval(()), Model({}), 0)
    with pytest.raises(ValueError, match="limits"):
        RetrievalAnswerService(Retrieval(()), Model({}), 10, 499)


@pytest.mark.asyncio
async def test_answer_rejects_blank_question_and_malformed_output() -> None:
    service = RetrievalAnswerService(Retrieval((_chunk(),)), Model({}), 10)
    with pytest.raises(ValueError, match="question"):
        await service.answer(" ")
    with pytest.raises(ValueError, match="missing"):
        await service.answer("问题")


@pytest.mark.asyncio
async def test_answer_context_budget_excludes_unavailable_citation() -> None:
    first = _chunk("mail:1")
    second = RetrievedChunk(
        uuid4(),
        "mail:2",
        "MICROSOFT_MAIL",
        "v1",
        NOW,
        "第二块" * 250,
        0.2,
        0.7,
        0.01,
    )
    model = Model({"answer": "越界", "citations": ["S2"], "insufficient_evidence": False})
    with pytest.raises(ValueError, match="outside retrieval"):
        await RetrievalAnswerService(
            Retrieval((first, second)), model, 10, max_context_chars=500
        ).answer("问题")


@pytest.mark.asyncio
async def test_answer_rejects_wrong_citation_and_evidence_flag_types() -> None:
    service = RetrievalAnswerService(
        Retrieval((_chunk(),)),
        Model({"answer": "回答", "citations": "S1", "insufficient_evidence": False}),
        10,
    )
    with pytest.raises(ValueError, match="contract"):
        await service.answer("问题")
