"""Deterministic RFC 5545 event mapping into the existing confirmation workflow."""

from qq_time_agent.modules.normalization.contracts import CalendarChangeKind, CalendarEventView
from qq_time_agent.modules.understanding.contracts import (
    CandidateDraft,
    CandidateKind,
    ExtractionDecision,
)


def calendar_event_decision(event: CalendarEventView) -> ExtractionDecision:
    if event.change_kind is CalendarChangeKind.CANCEL:
        return ExtractionDecision(None, 1.0, "calendar_cancellation_requires_existing_match", 0)
    if event.starts_at is None or event.ends_at is None:
        return ExtractionDecision(None, 1.0, "calendar_event_missing_time", 0)
    assumptions: tuple[str, ...] = ()
    if event.recurrence_rule is not None:
        assumptions += ("重复规则已保留;本次确认只处理首个事件时段",)
    if event.all_day:
        assumptions += ("全天事件使用本地午夜到次日午夜的闭开区间",)
    if event.sequence > 0 or event.recurrence_id is not None:
        assumptions += ("这是外部日历更新;执行前需按来源匹配现有日程",)
    draft = CandidateDraft(
        kind=CandidateKind.EVENT,
        title=event.title,
        starts_at=event.starts_at,
        ends_at=event.ends_at,
        deadline=None,
        timezone=event.timezone,
        location=event.location,
        participants=event.participants,
        estimated_duration_minutes=None,
        priority=None,
        allowed_windows=(),
        confidence=1.0,
        assumptions=assumptions,
        evidence=("deterministic RFC 5545 parse",),
    )
    return ExtractionDecision(draft, 1.0, None, 0)
