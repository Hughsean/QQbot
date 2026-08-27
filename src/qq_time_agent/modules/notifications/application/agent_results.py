"""Create durable, source-labelled notification intents for mail Agent results."""

from qq_time_agent.modules.notifications.application.ports import NotificationIntentRepository
from qq_time_agent.modules.notifications.contracts.agent_results import (
    AgentMailResultRequest,
    MailNotificationSource,
)
from qq_time_agent.modules.notifications.domain.models import (
    NotificationIntentDraft,
    NotificationKind,
)


class AgentMailResultNotificationService:
    def __init__(self, repository: NotificationIntentRepository) -> None:
        self._repository = repository

    async def schedule_agent_mail_result(self, request: AgentMailResultRequest) -> None:
        await self._repository.add_or_get(
            NotificationIntentDraft(
                request.user_id,
                _kind(request.source),
                f"agent-run:{request.run_id}",
                f"agent-run:{request.run_id}:result:v1",
                "agent-result-v2",
                _mail_result_body(request.subject, request.content),
                request.available_at,
            ),
            request.available_at,
        )


def _kind(source: MailNotificationSource) -> NotificationKind:
    if source is MailNotificationSource.OUTLOOK:
        return NotificationKind.OUTLOOK_MAIL_RESULT
    return NotificationKind.QQ_MAIL_RESULT


def _mail_result_body(subject: str, content: str) -> str:
    title = " ".join(subject.split())[:160] or "未命名邮件"
    separator = "\N{FULLWIDTH COLON}"
    return f"主题{separator}{title}\n\n{content.strip()}"[:4000]
