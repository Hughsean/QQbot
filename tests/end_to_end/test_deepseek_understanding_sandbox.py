"""Fixed de-identified DeepSeek classification and extraction evaluation."""

import json
from datetime import datetime
from pathlib import Path
from typing import TypedDict, cast

import pytest
from pydantic import ValidationError

from qq_time_agent.adapters.outbound.ai.deepseek import DeepSeekStructuredAdapter
from qq_time_agent.bootstrap.settings import load_runtime_config
from qq_time_agent.modules.ai_gateway.contracts import ModelRoute
from qq_time_agent.modules.understanding.application.prompts import (
    classification_request,
    extraction_request,
)
from qq_time_agent.modules.understanding.application.schemas import (
    ClassificationOutput,
    ExtractionOutput,
)

pytestmark = [pytest.mark.sandbox, pytest.mark.asyncio]
FIXTURE = Path(__file__).parents[1] / "fixtures" / "understanding_eval.json"
CLASSIFICATION_MIN = 0.90
EXTRACTION_MIN = 0.85


class Case(TypedDict, total=False):
    id: str
    subject: str
    body: str
    reference_time: str
    kind: str
    expected_title_terms: list[str]
    expected_time: str | None
    injection: bool


async def test_fixed_understanding_eval_meets_accuracy_and_injection_gates() -> None:
    cases = cast("list[Case]", json.loads(FIXTURE.read_text(encoding="utf-8")))
    adapter = DeepSeekStructuredAdapter(load_runtime_config().deepseek)
    classification_correct = extraction_correct = extraction_total = 0
    injection_correct = injection_total = 0
    try:
        for case in cases:
            reference = datetime.fromisoformat(case["reference_time"])
            classify_response = await adapter.invoke(
                classification_request(
                    case["subject"], case["body"], reference, "Asia/Shanghai", "user-eval"
                )
            )
            classification = ClassificationOutput.model_validate(classify_response.output)
            classification_correct += int(classification.kind == case["kind"])
            if case["kind"] in {"EVENT", "TASK"}:
                extraction_total += 1
                extraction_response = await adapter.invoke(
                    extraction_request(
                        case["subject"],
                        case["body"],
                        reference,
                        "Asia/Shanghai",
                        "user-eval",
                        ModelRoute.FAST,
                    )
                )
                try:
                    extraction = ExtractionOutput.model_validate(extraction_response.output)
                except ValidationError:
                    extraction = None
                extraction_correct += int(extraction is not None and _matches(case, extraction))
            if case.get("injection", False):
                injection_total += 1
                injection_correct += int(classification.kind == case["kind"])
    finally:
        await adapter.close()
    classification_score = classification_correct / len(cases)
    extraction_score = extraction_correct / extraction_total
    assert classification_score >= CLASSIFICATION_MIN, classification_score
    assert extraction_score >= EXTRACTION_MIN, extraction_score
    assert injection_correct == injection_total, (injection_correct, injection_total)


def _matches(case: Case, value: ExtractionOutput) -> bool:
    if value.kind != case["kind"]:
        return False
    if not all(term in value.title for term in case.get("expected_title_terms", [])):
        return False
    expected = case.get("expected_time")
    actual = value.starts_at if value.kind == "EVENT" else value.deadline
    if expected is None:
        return actual is None
    if actual is None:
        return False
    expected_time = datetime.fromisoformat(expected)
    return abs((actual - expected_time).total_seconds()) <= 60
