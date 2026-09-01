"""Deterministic notification templates and privacy-safe keys."""

from datetime import date, timedelta

from qq_time_agent.contracts.message_presentation import escape_origin_markers
from qq_time_agent.modules.agenda.contracts import AgendaConflictView, AgendaNotificationItem
from qq_time_agent.modules.connections.contracts import ReauthReminderCandidate
from qq_time_agent.modules.notifications.domain.models import NotificationKind

TEMPLATE_VERSION = "notification-v1"


def render_outbound(kind: NotificationKind, content: str) -> str:
    """Attach an unforgeable source label immediately before QQ delivery."""
    return f"[{_label(kind)}]\n{escape_origin_markers(content)}"


def render_reminder(
    title: str,
    starts_at: str,
    lead: timedelta,
    agenda_entry_id: object,
    reminder_id: object,
) -> str:
    separator = "\N{FULLWIDTH COLON}"
    return (
        "[日程提醒]\n"
        f"日程{separator}{escape_origin_markers(title)}\n"
        f"时间{separator}{starts_at} (北京时间)\n"
        f"{_lead_text(lead)}\n"
        f"回复“完成 {agenda_entry_id}”或“推迟 {reminder_id} 10”。"
    )


def _lead_text(lead: timedelta) -> str:
    minutes = max(0, round(lead.total_seconds() / 60))
    if minutes == 0:
        return "日程即将开始。"
    if minutes % 1440 == 0:
        return f"距离开始还有 {minutes // 1440} 天。"
    if minutes % 60 == 0:
        return f"距离开始还有 {minutes // 60} 小时。"
    return f"距离开始还有 {minutes} 分钟。"


def _label(kind: NotificationKind) -> str:
    labels = {
        NotificationKind.DAILY_DIGEST: "日程摘要",
        NotificationKind.MAIL_DIGEST: "邮件摘要",
        NotificationKind.AGENDA_CONFLICT: "日程冲突",
        NotificationKind.CONNECTION_REAUTH: "系统通知",
        NotificationKind.OUTLOOK_MAIL_RESULT: "邮件处理\N{FULLWIDTH VERTICAL LINE}Outlook",
        NotificationKind.QQ_MAIL_RESULT: "邮件处理\N{FULLWIDTH VERTICAL LINE}QQ邮箱",
        NotificationKind.AGENT_RESULT: "邮件处理",
    }
    return labels[kind]


def render_digest(day: date, entries: tuple[AgendaNotificationItem, ...]) -> str:
    lines = [f"{day.isoformat()} 日程摘要"]
    if not entries:
        lines.append("今日暂无已确认日程。")
    for value in entries:
        lines.append(f"{value.starts_at:%H:%M}-{value.ends_at:%H:%M} {value.title}")
    return "\n".join(lines)


def render_mail_digest(day: date, summaries: tuple[tuple[str, str], ...]) -> str:
    lines = [f"{day.isoformat()} 邮件摘要"]
    if not summaries:
        lines.append("暂无未即时推送的邮件处理结果。")
    lines.extend(f"{stamp} {summary}" for stamp, summary in summaries)
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
