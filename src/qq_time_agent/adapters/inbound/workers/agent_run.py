"""Durable AgentRun job handler."""

from uuid import UUID

from qq_time_agent.contracts.clock import Clock
from qq_time_agent.contracts.jobs import JobLease, JobQueue, JobRequest
from qq_time_agent.modules.agent.application.run_service import AgentRunService
from qq_time_agent.modules.agent.contracts import AgentContextPort
from qq_time_agent.modules.inbox.contracts import InboxContentPort, InboxSourcePort
from qq_time_agent.modules.notifications.application.ports import NotificationIntentRepository
from qq_time_agent.modules.notifications.domain.models import (
    NotificationIntentDraft,
    NotificationKind,
)


class AgentRunJobHandler:
    def __init__(
        self,
        runs: AgentRunService,
        content: InboxContentPort,
        context: AgentContextPort,
        source: InboxSourcePort | None = None,
        notifications: NotificationIntentRepository | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._runs = runs
        self._content = content
        self._context = context
        self._source = source
        self._notifications = notifications
        self._clock = clock

    async def __call__(self, job: JobLease) -> None:
        raw_run = job.payload.get("run_id")
        raw_item = job.payload.get("inbox_item_id")
        if not isinstance(raw_run, str) or not isinstance(raw_item, str):
            raise ValueError("agent-run requires run_id and inbox_item_id")
        item = await self._content.get_content(UUID(raw_item))
        if item is None:
            raise LookupError("AgentRun source content does not exist")
        context = await self._context.build(
            "owner", item.body_text, before=item.occurred_at, exclude_id=item.inbox_item_id
        )
        result = await self._runs.execute(UUID(raw_run), item.body_text, context)
        if self._notifications is not None and self._source is not None and self._clock is not None:
            source = await self._source.get_source(item.inbox_item_id)
            if source is not None and source.source_type in {"MICROSOFT_MAIL", "QQ_MAIL"}:
                now = self._clock.now()
                await self._notifications.add_or_get(
                    NotificationIntentDraft(
                        "owner",
                        NotificationKind.AGENT_RESULT,
                        f"agent-run:{raw_run}",
                        f"agent-run:{raw_run}:result:v1",
                        "agent-result-v1",
                        result.content[:4000],
                        now,
                    ),
                    now,
                )


class MailAgentRunScheduler:
    """Create an AgentRun after Understanding has accepted a mail item."""

    def __init__(
        self,
        runs: AgentRunService,
        content: InboxContentPort,
        source: InboxSourcePort,
        queue: JobQueue,
        clock: Clock,
    ) -> None:
        self._runs = runs
        self._content = content
        self._source = source
        self._queue = queue
        self._clock = clock

    async def schedule(self, inbox_item_id: UUID) -> None:
        source = await self._source.get_source(inbox_item_id)
        content = await self._content.get_content(inbox_item_id)
        if source is None or content is None:
            raise LookupError("mail AgentRun source is unavailable")
        if source.source_type not in {"MICROSOFT_MAIL", "QQ_MAIL"}:
            return
        run = await self._runs.ensure_run(inbox_item_id, "owner", source.source_type)
        await self._queue.enqueue(
            JobRequest(
                "agent-run",
                {"run_id": str(run.run_id), "inbox_item_id": str(inbox_item_id)},
                f"agent-run:{run.run_id}",
                self._clock.now(),
            )
        )
