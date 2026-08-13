from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from qq_time_agent.modules.understanding.application.schemas import (
    ClassificationOutput,
    ExtractionOutput,
)


def test_classification_normalizes_string_kind_only() -> None:
    output = ClassificationOutput.model_validate(
        {
            "kind": "event",
            "confidence": 0.9,
            "rationale": "fixed time",
            "temporal_ambiguity": False,
        }
    )
    assert output.kind == "EVENT"
    with pytest.raises(ValidationError):
        ClassificationOutput.model_validate(
            {
                "kind": 1,
                "confidence": 0.9,
                "rationale": "invalid",
                "temporal_ambiguity": False,
            }
        )


@pytest.mark.parametrize(
    "payload,message",
    [
        (
            {
                "kind": "EVENT",
                "title": "会面",
                "timezone": "Asia/Shanghai",
                "confidence": 0.9,
                "evidence": ["会面"],
            },
            "requires starts_at",
        ),
        (
            {
                "kind": "EVENT",
                "title": "会面",
                "starts_at": datetime(2026, 8, 20, tzinfo=UTC),
                "deadline": datetime(2026, 8, 21, tzinfo=UTC),
                "timezone": "Asia/Shanghai",
                "confidence": 0.9,
                "evidence": ["会面"],
            },
            "cannot include deadline",
        ),
        (
            {
                "kind": "TASK",
                "title": "写报告",
                "starts_at": datetime(2026, 8, 20, tzinfo=UTC),
                "timezone": "Asia/Shanghai",
                "confidence": 0.9,
                "evidence": ["写报告"],
            },
            "execution slot",
        ),
    ],
)
def test_extraction_rejects_kind_field_confusion(payload: dict[str, object], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        ExtractionOutput.model_validate(payload)


def test_non_string_optional_enum_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ExtractionOutput.model_validate(
            {
                "kind": "TASK",
                "title": "写报告",
                "timezone": "Asia/Shanghai",
                "priority": 1,
                "confidence": 0.9,
                "evidence": ["写报告"],
            }
        )
