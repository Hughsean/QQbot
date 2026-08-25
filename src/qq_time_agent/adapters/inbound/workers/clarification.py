"""Idempotently ask the owner for missing scheduling details."""

import logging

from qq_time_agent.modules.inbox.contracts import InboxProcessingQueryPort
from qq_time_agent.modules.notifications.contracts import NotificationPort

LOGGER = logging.getLogger(__name__)


class ClarificationWorker:
    def __init__(
        self, inbox: InboxProcessingQueryPort, notifications: NotificationPort
    ) -> None:
        self._inbox = inbox
        self._notifications = notifications

    async def run_once(self) -> int:
        sent = 0
        for source in await self._inbox.list_needs_review(20):
            try:
                await self._notifications.send_clarification(
                    "owner", str(source.inbox_item_id), _question(source.subject)
                )
            except Exception as exc:
                LOGGER.warning(
                    "Clarification delivery failed",
                    extra={
                        "inbox_item_id": str(source.inbox_item_id),
                        "failure_class": type(exc).__name__,
                    },
                )
            else:
                sent += 1
        return sent


def _question(subject: str) -> str:
    if "任务" in subject:
        return "我还不能确定这个任务的安排。请补充截止时间, 以及预计需要多长时间。"
    if "邮件" in subject or "QQ" not in subject:
        return "我需要更多信息才能安排。请补充这是日程还是任务, 并说明明确的时间范围。"
    return "我还不能确定你的意图。请说明这是日程事件还是待办任务, 并补充开始和结束时间。"
