from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from qq_time_agent.modules.understanding.contracts import CandidateKind
from qq_time_agent.modules.understanding.domain.candidates import Candidate


def _candidate(kind: CandidateKind) -> dict[str, object]:
    start = datetime(2026, 8, 19, 7, tzinfo=UTC)
    return {
        "inbox_item_id": uuid4(),
        "kind": kind,
        "title": "Review plan",
        "starts_at": start if kind is CandidateKind.EVENT else None,
        "ends_at": start + timedelta(hours=1) if kind is CandidateKind.EVENT else None,
        "deadline": start if kind is CandidateKind.TASK else None,
        "timezone": "Asia/Shanghai",
        "location": None,
        "participants": (),
        "estimated_duration_minutes": 60,
        "priority": "NORMAL",
        "allowed_windows": (),
        "confidence": 0.9,
        "assumptions": (),
        "evidence": ("Review plan",),
        "source_refs": ("inbox:test",),
    }


def test_event_and_task_invariants_are_distinct() -> None:
    event = Candidate.create(**_candidate(CandidateKind.EVENT))  # type: ignore[arg-type]
    task = Candidate.create(**_candidate(CandidateKind.TASK))  # type: ignore[arg-type]
    assert event.starts_at is not None and event.deadline is None
    assert task.deadline is not None and task.starts_at is None


def test_task_deadline_cannot_become_execution_slot() -> None:
    values = _candidate(CandidateKind.TASK)
    values["starts_at"] = datetime(2026, 8, 19, 7, tzinfo=UTC)
    with pytest.raises(ValueError, match="Event slot"):
        Candidate.create(**values)  # type: ignore[arg-type]


def test_candidate_rejects_naive_time_invalid_zone_and_confidence() -> None:
    values = _candidate(CandidateKind.EVENT)
    values["starts_at"] = datetime(2026, 8, 19, 7)
    with pytest.raises(ValueError, match="timezone-aware"):
        Candidate.create(**values)  # type: ignore[arg-type]
    values = _candidate(CandidateKind.TASK)
    values["timezone"] = "Mars/Olympus"
    with pytest.raises(ValueError, match="timezone is invalid"):
        Candidate.create(**values)  # type: ignore[arg-type]
    values = _candidate(CandidateKind.TASK)
    values["confidence"] = 1.1
    with pytest.raises(ValueError, match="bounded confidence"):
        Candidate.create(**values)  # type: ignore[arg-type]


def test_candidate_rejects_invalid_kind_specific_fields_and_duration() -> None:
    values = _candidate(CandidateKind.EVENT)
    values["ends_at"] = values["starts_at"]
    with pytest.raises(ValueError, match="ordered start and end"):
        Candidate.create(**values)  # type: ignore[arg-type]
    values = _candidate(CandidateKind.EVENT)
    values["deadline"] = datetime(2026, 8, 20, tzinfo=UTC)
    with pytest.raises(ValueError, match="Task deadline"):
        Candidate.create(**values)  # type: ignore[arg-type]
    values = _candidate(CandidateKind.TASK)
    values["estimated_duration_minutes"] = 0
    with pytest.raises(ValueError, match="duration must be positive"):
        Candidate.create(**values)  # type: ignore[arg-type]
