"""Deterministic notification templates and privacy-safe keys."""

from datetime import date

from qq_time_agent.modules.agenda.contracts import AgendaConflictView, AgendaNotificationItem
from qq_time_agent.modules.connections.contracts import ReauthReminderCandidate

TEMPLATE_VERSION = "notification-v1"


def render_digest(day: date, entries: tuple[AgendaNotificationItem, ...]) -> str:
    lines = [f"{day.isoformat()} 日程摘要"]
    if not entries:
        lines.append("今日暂无已确认日程。")
    for value in entries:
        lines.append(f"{value.starts_at:%H:%M}-{value.ends_at:%H:%M} {value.title}")
    return "\n".join(lines)


def render_conflict(value: AgendaConflictView) -> str:
    first, second = sorted(
        (value.first, value.second),
        key=lambda item: (item.starts_at, item.ends_at, str(item.agenda_entry_id)),
    )
    return (
        "日程冲突提醒\n"
        f"{first.starts_at:%m-%d %H:%M}-{first.ends_at:%H:%M} {first.title}\n"
        f"{second.starts_at:%m-%d %H:%M}-{second.ends_at:%H:%M} {second.title}"
    )


def conflict_key(value: AgendaConflictView) -> str:
    ordered = sorted((value.first, value.second), key=lambda item: str(item.agenda_entry_id))
    return (
        f"agenda-conflict:{ordered[0].agenda_entry_id}:v{ordered[0].version}:"
        f"{ordered[1].agenda_entry_id}:v{ordered[1].version}:{TEMPLATE_VERSION}"
    )


def render_reauth(value: ReauthReminderCandidate) -> str:
    return f"邮箱连接需要重新授权: {value.display_label} ({value.provider})"
