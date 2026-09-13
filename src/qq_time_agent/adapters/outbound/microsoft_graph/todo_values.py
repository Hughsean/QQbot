"""Microsoft Graph To Do paths and write payloads."""

from datetime import UTC, datetime
from urllib.parse import quote

from qq_time_agent.modules.task_projection.contracts import ExternalTaskDraft

LISTS_PATH = "/v1.0/me/todo/lists"


def task_payload(draft: ExternalTaskDraft) -> dict[str, object]:
    return {
        "title": draft.title,
        "body": {
            "contentType": "text",
            "content": "由小智从内部日程同步。请仅使用完成复选框。\n\n"
            f"同步标记: {draft.stable_marker}",
        },
        "startDateTime": _graph_time(draft.starts_at),
        "dueDateTime": _graph_time(draft.ends_at),
        "isReminderOn": False,
    }


def tasks_path(list_ref: str) -> str:
    return f"{LISTS_PATH}/{quote(list_ref, safe='')}/tasks"


def task_path(list_ref: str, task_ref: str) -> str:
    return f"{tasks_path(list_ref)}/{quote(task_ref, safe='')}"


def task_delta_path(list_ref: str) -> str:
    return f"{tasks_path(list_ref)}/delta"


def _graph_time(value: datetime) -> dict[str, str]:
    normalized = value.astimezone(UTC).replace(tzinfo=None).isoformat(timespec="seconds")
    return {"dateTime": normalized, "timeZone": "UTC"}
