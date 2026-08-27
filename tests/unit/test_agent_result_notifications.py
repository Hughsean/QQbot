from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from qq_time_agent.modules.notifications.application.agent_results import (
    AgentMailResultNotificationService,
)
from qq_time_agent.modules.notifications.contracts import (
    AgentMailResultRequest,
    MailNotificationSource,
)
from qq_time_agent.modules.notifications.domain.models import (
    NotificationIntent,
    NotificationIntentDraft,
)

NOW = datetime(2026, 8, 27, tzinfo=UTC)


@dataclass
class Repository:
    drafts: list[NotificationIntentDraft] = field(default_factory=list)

    async def add_or_get(self, draft: NotificationIntentDraft, now: datetime) -> NotificationIntent:
        self.drafts.append(draft)
        return NotificationIntent.create(draft, now)

    async def lease_due(
        self, now: datetime, owner: str, duration: timedelta, limit: int
    ) -> tuple[NotificationIntent, ...]:
        del now, owner, duration, limit
        return ()

    async def save(self, intent: NotificationIntent, expected_version: int) -> None:
        del intent, expected_version

    async def has_open(self, subject_key: str) -> bool:
        del subject_key
        return False

    async def has_recent_sent(self, subject_key: str, since: datetime) -> bool:
        del subject_key, since
        return False

    async def recover_expired(self, now: datetime, limit: int) -> int:
        del now, limit
        return 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("source", "expected_kind"),
    [
        (MailNotificationSource.OUTLOOK, "OUTLOOK_MAIL_RESULT"),
        (MailNotificationSource.QQ_MAIL, "QQ_MAIL_RESULT"),
    ],
)
async def test_mail_result_intent_preserves_provider_origin(
    source: MailNotificationSource, expected_kind: str
) -> None:
    repository = Repository()
    run_id = uuid4()
    await AgentMailResultNotificationService(repository).schedule_agent_mail_result(
        AgentMailResultRequest("owner", run_id, source, "  项目评审  ", "处理完成", NOW)
    )
    draft = repository.drafts[0]
    assert draft.kind.value == expected_kind
    assert draft.idempotency_key == f"agent-run:{run_id}:result:v1"
    assert draft.content == "主题\N{FULLWIDTH COLON}项目评审\n\n处理完成"
