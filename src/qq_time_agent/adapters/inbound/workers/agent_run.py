"""Durable AgentRun job handler."""

from uuid import UUID

from qq_time_agent.adapters.inbound.workers.runner import (
    PermanentJobError,
    RetryableJobError,
)
from qq_time_agent.contracts.clock import Clock
from qq_time_agent.contracts.jobs import JobLease, JobQueue, JobRequest
from qq_time_agent.modules.agent.application.run_service import AgentRunService
from qq_time_agent.modules.agent.contracts import (
    AgentContextPort,
    AgentDelivery,
    AgentFinal,
    AgentResponseProtocolError,
    AgentRun,
    AgentRunExecution,
    AgentRunExecutionPort,
    AgentRunExecutionStatus,
    AgentRunStatus,
)
from qq_time_agent.modules.ai_gateway.contracts import ModelFailure
from qq_time_agent.modules.inbox.contracts import (
    InboxContentPort,
    InboxContentView,
    InboxSourcePort,
    MailDeliverySourcePort,
)
from qq_time_agent.modules.notifications.application.mail_delivery import MailDeliveryPolicy
from qq_time_agent.modules.notifications.contracts import (
    AgentMailResultRequest,
    MailNotificationSource,
    NotificationIntentCommandPort,
)


class AgentRunJobHandler:
    def __init__(
        self,
        runs: AgentRunExecutionPort,
        content: InboxContentPort,
        context: AgentContextPort,
        delivery_source: MailDeliverySourcePort | None = None,
        notifications: NotificationIntentCommandPort | None = None,
        clock: Clock | None = None,
        delivery_policy: MailDeliveryPolicy | None = None,
    ) -> None:
        self._runs = runs
        self._content = content
        self._context = context
        self._delivery_source = delivery_source
        self._notifications = notifications
        self._clock = clock
        self._delivery_policy = delivery_policy

    async def __call__(self, job: JobLease) -> None:
        run_id, item_id = _payload_ids(job)
        run = await self._runs.get(run_id)
        if run is None:
            raise PermanentJobError("MissingAgentRun")
        persisted = _persisted_final(run)
        if persisted is not None:
            effective = await self._freeze_effective_delivery(run, persisted)
            if effective is AgentDelivery.HOLD:
                return
            item = await self._require_content(item_id)
            await self._schedule_notification(run, item, persisted)
            return

        item = await self._require_content(item_id)
        context = await self._context.build(
            "owner",
            item.body_text,
            before=item.occurred_at,
            exclude_id=item.inbox_item_id,
            conversation_id=run.conversation_id,
            event_case_id=run.event_case_id,
        )
        try:
            raw_outcome = await self._runs.execute(run_id, item.body_text, context)
            outcome = _execution_outcome(raw_outcome)
        except AgentResponseProtocolError as exc:
            raise PermanentJobError("InvalidAgentResponse") from exc
        except ModelFailure as exc:
            if exc.failure_class in {
                "TimeoutOrNetwork",
                "RateLimit",
                "ProviderUnavailable",
                "UnexpectedProvider",
            }:
                raise RetryableJobError(exc.failure_class) from exc
            raise PermanentJobError(exc.failure_class) from exc
        if outcome.status is AgentRunExecutionStatus.IN_PROGRESS:
            raise RetryableJobError("AgentRunInProgress")
        if outcome.final is None:
            raise PermanentJobError("MalformedAgentRunResult")
        effective_delivery = await self._freeze_effective_delivery(run, outcome.final)
        if effective_delivery is AgentDelivery.NOTIFY:
            await self._schedule_notification(run, item, outcome.final)

    async def _freeze_effective_delivery(
        self, run: AgentRun, result: AgentFinal
    ) -> AgentDelivery:
        if run.effective_delivery is not None:
            return run.effective_delivery
        proposed = await self._effective_delivery(run, result)
        try:
            return await self._runs.freeze_effective_delivery(run.run_id, proposed)
        except Exception as exc:
            raise RetryableJobError("AgentDeliveryPersistenceFailed") from exc

    async def _effective_delivery(
        self, run: AgentRun, result: AgentFinal
    ) -> AgentDelivery:
        if self._delivery_policy is None or self._delivery_source is None:
            return result.delivery
        source = await self._delivery_source.get_mail_delivery_source(
            run.user_id, run.inbox_item_id
        )
        if source is None:
            raise PermanentJobError("MissingAgentNotificationSource")
        return await self._delivery_policy.resolve(
            run.user_id, source.sender, source.subject, result.delivery
        )

    async def _require_content(self, item_id: UUID) -> InboxContentView:
        item = await self._content.get_content(item_id)
        if item is None:
            raise PermanentJobError("MissingAgentRunSource")
        return item

    async def _schedule_notification(
        self, run: AgentRun, item: InboxContentView, result: AgentFinal
    ) -> None:
        if self._notifications is None or self._delivery_source is None or self._clock is None:
            raise PermanentJobError("AgentNotificationUnavailable")
        try:
            source = await self._delivery_source.get_mail_delivery_source(
                run.user_id, item.inbox_item_id
            )
        except Exception as exc:
            raise RetryableJobError("AgentNotificationSourceUnavailable") from exc
        if source is None:
            raise PermanentJobError("MissingAgentNotificationSource")
        notification_source = _mail_source(source.source_type)
        if notification_source is None:
            raise PermanentJobError("UnsupportedAgentNotificationSource")
        try:
            await self._notifications.schedule_agent_mail_result(
                AgentMailResultRequest(
                    "owner",
                    run.run_id,
                    notification_source,
                    item.subject,
                    result.content,
                    self._clock.now(),
                )
            )
        except Exception as exc:
            raise RetryableJobError("AgentNotificationPersistenceFailed") from exc


class MailAgentRunScheduler:
    """Create an AgentRun immediately after deterministic mail normalization."""

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
        run = await self._runs.ensure_run(
            inbox_item_id,
            "owner",
            source.source_type,
            conversation_key=source.thread_id or f"mail:{source.source_type}",
            event_key=source.thread_id or source.external_id,
            occurred_at=source.occurred_at,
        )
        await self._queue.enqueue(
            JobRequest(
                "agent-run",
                {"run_id": str(run.run_id), "inbox_item_id": str(inbox_item_id)},
                f"agent-run:{run.run_id}",
                self._clock.now(),
            )
        )


def _payload_ids(job: JobLease) -> tuple[UUID, UUID]:
    raw_run = job.payload.get("run_id")
    raw_item = job.payload.get("inbox_item_id")
    if not isinstance(raw_run, str) or not isinstance(raw_item, str):
        raise PermanentJobError("MalformedAgentRunPayload")
    try:
        return UUID(raw_run), UUID(raw_item)
    except ValueError as exc:
        raise PermanentJobError("MalformedAgentRunPayload") from exc


def _persisted_final(run: AgentRun) -> AgentFinal | None:
    if run.status is not AgentRunStatus.COMPLETED:
        return None
    if run.final_content is None or run.final_delivery is None:
        raise PermanentJobError("MalformedCompletedAgentRun")
    return AgentFinal(run.final_content, run.final_delivery)


def _execution_outcome(value: AgentRunExecution | AgentFinal) -> AgentRunExecution:
    if isinstance(value, AgentRunExecution):
        return value
    return AgentRunExecution(AgentRunExecutionStatus.EXECUTED, value)


def _mail_source(source_type: str) -> MailNotificationSource | None:
    if source_type == "MICROSOFT_MAIL":
        return MailNotificationSource.OUTLOOK
    if source_type == "QQ_MAIL":
        return MailNotificationSource.QQ_MAIL
    return None
