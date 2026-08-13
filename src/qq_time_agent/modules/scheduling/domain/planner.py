"""Deterministic hard-constraint planner on a 15-minute grid."""

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from qq_time_agent.modules.agenda.contracts import BusyInterval
from qq_time_agent.modules.identity.contracts import UserPreferencesView
from qq_time_agent.modules.scheduling.contracts import ProposalConflict, ProposalSlot
from qq_time_agent.modules.understanding.contracts import EventCandidateView, TaskCandidateView

GRID_MINUTES = 15
MAX_SEARCH_DAYS = 14


@dataclass(frozen=True, slots=True)
class Plan:
    recommended: ProposalSlot | None
    alternatives: tuple[ProposalSlot, ...]
    conflicts: tuple[ProposalConflict, ...]
    rationale: str
    assumptions: tuple[str, ...]
    snapshot: dict[str, object]


def plan_event(
    candidate: EventCandidateView,
    busy: tuple[BusyInterval, ...],
    preferences: UserPreferencesView,
) -> Plan:
    slot = ProposalSlot(candidate.starts_at, candidate.ends_at, candidate.timezone)
    conflicts = tuple(_conflict(value) for value in busy if _overlaps(slot, value))
    rationale = (
        "固定事件时间保持不变; 存在冲突, 需要确认或修改"
        if conflicts
        else "固定事件时间保持不变且与当前 Agenda 无冲突"
    )
    recommended = None if conflicts else slot
    return Plan(
        recommended, (), conflicts, rationale, candidate.assumptions, _snapshot(preferences)
    )


def plan_task(
    candidate: TaskCandidateView,
    busy: tuple[BusyInterval, ...],
    preferences: UserPreferencesView,
    now: datetime,
) -> Plan:
    zone = ZoneInfo(preferences.timezone)
    local_now = now.astimezone(zone)
    duration = candidate.estimated_duration_minutes or preferences.default_task_minutes
    assumptions = candidate.assumptions
    if candidate.estimated_duration_minutes is None:
        assumptions += (f"未提供预计耗时, 使用默认 {duration} 分钟",)
    deadline = None if candidate.deadline is None else candidate.deadline.astimezone(zone)
    default_horizon = local_now + timedelta(days=MAX_SEARCH_DAYS)
    horizon = min(default_horizon, deadline) if deadline is not None else default_horizon
    windows = _candidate_windows(candidate.allowed_windows, zone)
    slots = _free_slots(local_now, horizon, duration, preferences, busy, windows, zone)
    chosen = slots[:3]
    conflicts = () if chosen else tuple(_conflict(value) for value in busy)
    rationale = (
        "按工作时间、午休、截止时间和 Agenda 空闲区间选择最早可用时段"
        if chosen
        else "在允许窗口、工作时间和截止时间内没有满足时长的空闲时段"
    )
    return Plan(
        chosen[0] if chosen else None,
        tuple(chosen[1:]),
        conflicts,
        rationale,
        assumptions,
        _snapshot(preferences, deadline, duration, windows),
    )


def _free_slots(
    now: datetime,
    horizon: datetime,
    duration_minutes: int,
    preferences: UserPreferencesView,
    busy: tuple[BusyInterval, ...],
    windows: tuple[tuple[datetime, datetime], ...],
    zone: ZoneInfo,
) -> list[ProposalSlot]:
    current = _ceil_grid(now)
    duration = timedelta(minutes=duration_minutes)
    result: list[ProposalSlot] = []
    while current + duration <= horizon and len(result) < 3:
        end = current + duration
        slot = ProposalSlot(current, end, str(zone))
        if _allowed(slot, preferences, busy, windows):
            result.append(slot)
            current = end
        else:
            current += timedelta(minutes=GRID_MINUTES)
    return result


def _allowed(
    slot: ProposalSlot,
    preferences: UserPreferencesView,
    busy: tuple[BusyInterval, ...],
    windows: tuple[tuple[datetime, datetime], ...],
) -> bool:
    local_start, local_end = slot.starts_at.timetz(), slot.ends_at.timetz()
    weekday = slot.starts_at.weekday()
    within_work = (
        weekday in preferences.working_weekdays
        and slot.starts_at.date() == slot.ends_at.date()
        and _plain(local_start) >= preferences.work_start
        and _plain(local_end) <= preferences.work_end
    )
    lunch_overlap = (
        _plain(local_start) < preferences.lunch_end and _plain(local_end) > preferences.lunch_start
    )
    available = all(not _overlaps(slot, value) for value in busy)
    allowed_window = not windows or any(
        slot.starts_at >= start and slot.ends_at <= end for start, end in windows
    )
    return within_work and not lunch_overlap and available and allowed_window


def _candidate_windows(
    values: tuple[str, ...], zone: ZoneInfo
) -> tuple[tuple[datetime, datetime], ...]:
    result: list[tuple[datetime, datetime]] = []
    for value in values:
        parts = value.split("/", 1)
        if len(parts) != 2:
            raise ValueError("Task allowed window must be an ISO start/end interval")
        start, end = (datetime.fromisoformat(part).astimezone(zone) for part in parts)
        if end <= start:
            raise ValueError("Task allowed window must be ordered")
        result.append((start, end))
    return tuple(result)


def _ceil_grid(value: datetime) -> datetime:
    base = value.replace(second=0, microsecond=0)
    remainder = base.minute % GRID_MINUTES
    if remainder or value.second or value.microsecond:
        base += timedelta(minutes=GRID_MINUTES - remainder)
    return base


def _overlaps(slot: ProposalSlot, busy: BusyInterval) -> bool:
    return slot.starts_at < busy.ends_at and slot.ends_at > busy.starts_at


def _conflict(value: BusyInterval) -> ProposalConflict:
    return ProposalConflict(
        value.agenda_entry_id,
        value.title,
        value.starts_at,
        value.ends_at,
        "与现有不可移动 Agenda 条目重叠",
    )


def _snapshot(
    value: UserPreferencesView,
    deadline: datetime | None = None,
    duration: int | None = None,
    windows: tuple[tuple[datetime, datetime], ...] = (),
) -> dict[str, object]:
    return {
        "timezone": value.timezone,
        "work_start": value.work_start.isoformat(),
        "work_end": value.work_end.isoformat(),
        "lunch_start": value.lunch_start.isoformat(),
        "lunch_end": value.lunch_end.isoformat(),
        "working_weekdays": list(value.working_weekdays),
        "deadline": None if deadline is None else deadline.isoformat(),
        "duration_minutes": duration,
        "allowed_windows": [(start.isoformat(), end.isoformat()) for start, end in windows],
        "grid_minutes": GRID_MINUTES,
    }


def _plain(value: time) -> time:
    return value.replace(tzinfo=None)
