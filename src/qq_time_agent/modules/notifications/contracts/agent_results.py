"""Public command contract for Agent-originated mail notifications."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID


class MailNotificationSource(StrEnum):
    OUTLOOK = "OUTLOOK"
    QQ_MAIL = "QQ_MAIL"


@dataclass(frozen=True, slots=True)
class AgentMailResultRequest:
    user_id: str
    run_id: UUID
    source: MailNotificationSource
    subject: str
    content: str
    available_at: datetime

    def __post_init__(self) -> None:
        if not self.user_id.strip() or not self.subject.strip() or not self.content.strip():
            raise ValueError("agent mail notification fields are required")
        if self.available_at.tzinfo is None or self.available_at.utcoffset() is None:
            raise ValueError("agent mail notification time must be timezone-aware")


class NotificationIntentCommandPort(Protocol):
    async def schedule_agent_mail_result(self, request: AgentMailResultRequest) -> None: ...
