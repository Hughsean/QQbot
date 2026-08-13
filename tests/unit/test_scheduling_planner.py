from datetime import UTC, datetime, time, timedelta
from uuid import uuid4

import pytest

from qq_time_agent.modules.agenda.contracts import BusyInterval
from qq_time_agent.modules.identity.contracts import UserPreferencesView
from qq_time_agent.modules.scheduling.contracts import ProposalSlot
from qq_time_agent.modules.scheduling.domain.models import SchedulingProposal
from qq_time_agent.modules.scheduling.domain.planner import plan_event, plan_task
from qq_time_agent.modules.understanding.contracts import (
    EventCandidateView,
    TaskCandidateView,
)


def _preferences() -> UserPreferencesView:
    return UserPreferencesView(
        "owner",
        "Asia/Shanghai",
        time(9),
        time(18),
        time(12),
        time(13, 30),
        (0, 1, 2, 3, 4),
        30,
        60,
    )


def _event(start: datetime, end: datetime) -> EventCandidateView:
    return EventCandidateView(
        uuid4(),
        uuid4(),
        "方案评审",
        start,
        end,
        "Asia/Shanghai",
        None,
        (),
        0.9,
        (),
        ("方案评审",),
        ("inbox:event",),
    )


def _task(
    deadline: datetime | None,
    duration: int | None = 60,
    windows: tuple[str, ...] = (),
) -> TaskCandidateView:
    return TaskCandidateView(
        uuid4(),
        uuid4(),
        "写报告",
        deadline,
        duration,
        "NORMAL",
        windows,
        0.9,
        (),
        ("写报告",),
        ("inbox:task",),
    )


def test_fixed_event_is_not_moved_and_conflict_blocks_recommendation() -> None:
    start = datetime.fromisoformat("2026-08-19T15:00:00+08:00")
    end = datetime.fromisoformat("2026-08-19T16:00:00+08:00")
    busy = (BusyInterval(uuid4(), "已有会议", start, end, False),)
    conflicted = plan_event(_event(start, end), busy, _preferences())
    assert conflicted.recommended is None
    assert len(conflicted.conflicts) == 1 and conflicted.alternatives == ()
    clear = plan_event(_event(start, end), (), _preferences())
    assert clear.recommended is not None
    assert clear.recommended.starts_at == start


def test_task_slots_obey_work_lunch_busy_deadline_and_two_alternatives() -> None:
    now = datetime.fromisoformat("2026-08-13T08:53:00+08:00")
    deadline = datetime.fromisoformat("2026-08-13T17:00:00+08:00")
    busy = (
        BusyInterval(
            uuid4(),
            "晨会",
            datetime.fromisoformat("2026-08-13T09:00:00+08:00"),
            datetime.fromisoformat("2026-08-13T10:00:00+08:00"),
            False,
        ),
    )
    plan = plan_task(_task(deadline), busy, _preferences(), now)
    assert plan.recommended is not None
    slots = (plan.recommended, *plan.alternatives)
    assert len(plan.alternatives) == 2
    assert slots[0].starts_at.isoformat() == "2026-08-13T10:00:00+08:00"
    assert all(slot.ends_at <= deadline for slot in slots)
    assert all(not (slot.starts_at.hour < 13 and slot.ends_at.hour > 12) for slot in slots)


def test_task_deadline_is_not_used_as_event_slot_and_missing_duration_is_explicit() -> None:
    now = datetime.fromisoformat("2026-08-13T09:00:00+08:00")
    deadline = datetime.fromisoformat("2026-08-13T10:00:00+08:00")
    plan = plan_task(_task(deadline, None), (), _preferences(), now)
    assert plan.recommended is not None
    assert plan.recommended.starts_at == now
    assert plan.recommended.ends_at == deadline
    assert "默认 60 分钟" in plan.assumptions[-1]


def test_allowed_window_and_no_space_are_explained() -> None:
    now = datetime.fromisoformat("2026-08-13T09:00:00+08:00")
    deadline = datetime.fromisoformat("2026-08-13T11:00:00+08:00")
    window = "2026-08-13T10:00:00+08:00/2026-08-13T11:00:00+08:00"
    planned = plan_task(_task(deadline, 60, (window,)), (), _preferences(), now)
    assert planned.recommended is not None
    assert planned.recommended.starts_at.hour == 10
    blocked = (
        BusyInterval(
            uuid4(),
            "占满",
            datetime.fromisoformat("2026-08-13T09:00:00+08:00"),
            deadline,
            False,
        ),
    )
    no_space = plan_task(_task(deadline, 60), blocked, _preferences(), now)
    assert no_space.recommended is None and no_space.conflicts
    assert "没有" in no_space.rationale


@pytest.mark.parametrize(
    "window",
    ["not-an-interval", "2026-08-13T11:00:00+08:00/2026-08-13T10:00:00+08:00"],
)
def test_invalid_allowed_windows_are_rejected(window: str) -> None:
    with pytest.raises(ValueError, match="allowed window"):
        plan_task(
            _task(None, 60, (window,)),
            (),
            _preferences(),
            datetime(2026, 8, 13, tzinfo=UTC),
        )


def test_weekend_and_cross_day_duration_never_pass_work_hours() -> None:
    friday = datetime.fromisoformat("2026-08-14T17:00:00+08:00")
    monday = datetime.fromisoformat("2026-08-17T18:00:00+08:00")
    plan = plan_task(_task(monday, 16 * 60), (), _preferences(), friday)
    assert plan.recommended is None
    weekend = datetime.fromisoformat("2026-08-15T09:00:00+08:00")
    weekend_deadline = datetime.fromisoformat("2026-08-16T18:00:00+08:00")
    weekend_plan = plan_task(_task(weekend_deadline, 60), (), _preferences(), weekend)
    assert weekend_plan.recommended is None


def test_no_deadline_search_horizon_is_bounded_to_fourteen_days() -> None:
    now = datetime.fromisoformat("2026-08-13T09:00:00+08:00")
    plan = plan_task(_task(None, 60), (), _preferences(), now)
    assert plan.recommended is not None
    assert plan.snapshot["deadline"] is None
    assert plan.recommended.starts_at <= now + timedelta(days=14)


def test_proposal_rejects_invalid_aggregate_fields() -> None:
    now = datetime(2026, 8, 13, tzinfo=UTC)
    proposal = _proposal(now)
    proposal.candidate_kind = "NOTE"
    with pytest.raises(ValueError, match="kind"):
        proposal.validate()
    proposal = _proposal(now)
    proposal.title = ""
    with pytest.raises(ValueError, match="required"):
        proposal.validate()
    proposal = _proposal(now)
    proposal.alternative_slots = (_slot(now), _slot(now), _slot(now))
    with pytest.raises(ValueError, match="alternatives"):
        proposal.validate()
    proposal = _proposal(now)
    proposal.expires_at = datetime(2026, 8, 14)
    with pytest.raises(ValueError, match="timezone-aware"):
        proposal.validate()


@pytest.mark.parametrize(
    "slot",
    [
        ProposalSlot(
            datetime(2026, 8, 13, tzinfo=UTC),
            datetime(2026, 8, 13, 1, tzinfo=UTC),
            "Invalid/Zone",
        ),
        ProposalSlot(datetime(2026, 8, 13), datetime(2026, 8, 13, 1), "UTC"),
        ProposalSlot(
            datetime(2026, 8, 13, 1, tzinfo=UTC),
            datetime(2026, 8, 13, tzinfo=UTC),
            "UTC",
        ),
    ],
)
def test_proposal_rejects_invalid_slots(slot: ProposalSlot) -> None:
    with pytest.raises(ValueError, match=r"timezone|end"):
        SchedulingProposal.create(
            "owner",
            uuid4(),
            "TASK",
            "写报告",
            slot,
            (),
            (),
            "按偏好排程",
            (),
            ("inbox:task",),
            datetime(2026, 8, 14, tzinfo=UTC),
            {},
        )


def _slot(now: datetime) -> ProposalSlot:
    return ProposalSlot(now, now + timedelta(hours=1), "UTC")


def _proposal(now: datetime) -> SchedulingProposal:
    return SchedulingProposal.create(
        "owner",
        uuid4(),
        "TASK",
        "写报告",
        None,
        (),
        (),
        "按偏好排程",
        (),
        ("inbox:task",),
        now + timedelta(days=1),
        {},
    )
