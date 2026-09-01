from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from qq_time_agent.adapters.inbound.workers.agent_run import AgentRunJobHandler
from qq_time_agent.adapters.inbound.workers.runner import (
    PermanentJobError,
    RetryableJobError,
)
from qq_time_agent.contracts.jobs import JobLease
from qq_time_agent.modules.agent.contracts import (
    AgentDelivery,
    AgentFinal,
    AgentResponseProtocolError,
    AgentRun,
    AgentRunStatus,
)
from qq_time_agent.modules.ai_gateway.contracts import ModelFailure
from qq_time_agent.modules.inbox.contracts import (
    InboxContentView,
    InboxSourceView,
    MailDeliverySourceView,
)
from qq_time_agent.modules.notifications.contracts import AgentMailResultRequest

NOW = datetime(2026, 8, 26, tzinfo=UTC)


@dataclass
class Runs:
    run: AgentRun
    result: AgentFinal
    failure: Exception | None = None

    async def get(self, run_id: UUID) -> AgentRun | None:
        return self.run if run_id == self.run.run_id else None

    async def execute(self, run_id: UUID, message: str, context: str = "") -> AgentFinal:
        assert run_id == self.run.run_id and message == "邮件正文" and context == "事件上下文"
        if self.failure is not None:
            raise self.failure
        self.run.status = AgentRunStatus.COMPLETED
        self.run.final_content = self.result.content
        self.run.final_delivery = self.result.delivery
        return self.result

    async def freeze_effective_delivery(
        self, run_id: UUID, delivery: AgentDelivery
    ) -> AgentDelivery:
        assert run_id == self.run.run_id
        if self.run.effective_delivery is None:
            self.run.effective_delivery = delivery
        return self.run.effective_delivery


@dataclass
class Content:
    item: InboxContentView

    async def get_content(self, inbox_item_id: UUID) -> InboxContentView | None:
        return self.item if inbox_item_id == self.item.inbox_item_id else None


class Context:
    async def build(self, *args: object, **kwargs: object) -> str:
        del args, kwargs
        return "事件上下文"


@dataclass
class Source:
    value: InboxSourceView

    async def get_source(self, inbox_item_id: UUID) -> InboxSourceView | None:
        return self.value if inbox_item_id == self.value.inbox_item_id else None

    async def get_mail_delivery_source(
        self, user_id: str, inbox_item_id: UUID
    ) -> MailDeliverySourceView | None:
        del user_id
        source = await self.get_source(inbox_item_id)
        if source is None:
            return None
        return MailDeliverySourceView(
            source.inbox_item_id,
            source.source_type,
            "sender@example.com",
            source.subject,
        )


@dataclass
class Notifications:
    requests: list[AgentMailResultRequest] = field(default_factory=list)

    async def schedule_agent_mail_result(self, request: AgentMailResultRequest) -> None:
        self.requests.append(request)


class Clock:
    def now(self) -> datetime:
        return NOW


def _handler(
    delivery: AgentDelivery,
    source_type: str = "MICROSOFT_MAIL",
    failure: Exception | None = None,
) -> tuple[AgentRunJobHandler, JobLease, Notifications]:
    item_id = uuid4()
    run_id = uuid4()
    item = InboxContentView(
        item_id,
        "项目评审时间调整",
        "邮件正文",
        None,
        "text/plain",
        NOW,
        "mail:test",
        "hash",
        None,
    )
    run = AgentRun(run_id, item_id, "owner", source_type, AgentRunStatus.PENDING, 0)
    source = InboxSourceView(
        item_id, source_type, "message", "thread", "masked", item.subject, NOW, "NORMALIZED", False
    )
    notifications = Notifications()
    handler = AgentRunJobHandler(
        Runs(run, AgentFinal("已识别到时间变更", delivery), failure),
        Content(item),
        Context(),
        Source(source),
        notifications,
        Clock(),
    )
    job = JobLease(
        uuid4(), "agent-run", {"run_id": str(run_id), "inbox_item_id": str(item_id)}, "worker", 1, 5
    )
    return handler, job, notifications


@pytest.mark.asyncio
async def test_mail_agent_hold_result_never_creates_unsolicited_notification() -> None:
    handler, job, notifications = _handler(AgentDelivery.HOLD)
    await handler(job)
    assert notifications.requests == []


@pytest.mark.asyncio
async def test_mail_agent_notification_is_anchored_to_its_subject() -> None:
    handler, job, notifications = _handler(AgentDelivery.NOTIFY)
    await handler(job)
    assert len(notifications.requests) == 1
    request = notifications.requests[0]
    assert request.source.value == "OUTLOOK"
    assert request.subject == "项目评审时间调整"
    assert request.content == "已识别到时间变更"


@pytest.mark.asyncio
async def test_non_mail_agent_notification_is_permanently_rejected() -> None:
    handler, job, notifications = _handler(AgentDelivery.NOTIFY, "QQ_DIRECT")
    with pytest.raises(PermanentJobError, match="UnsupportedAgentNotificationSource"):
        await handler(job)
    assert notifications.requests == []


@pytest.mark.asyncio
async def test_invalid_agent_response_is_permanently_classified_without_notification() -> None:
    handler, job, notifications = _handler(
        AgentDelivery.HOLD, failure=AgentResponseProtocolError("invalid")
    )
    with pytest.raises(PermanentJobError, match="InvalidAgentResponse"):
        await handler(job)
    assert notifications.requests == []


@pytest.mark.asyncio
async def test_completed_hold_short_circuits_before_source_content() -> None:
    handler, job, _ = _handler(AgentDelivery.HOLD)
    runs = handler._runs
    assert isinstance(runs, Runs)
    runs.run.status = AgentRunStatus.COMPLETED
    runs.run.final_content = "已完成"
    runs.run.final_delivery = AgentDelivery.HOLD
    handler._content = Content(
        InboxContentView(uuid4(), "", "", None, "text/plain", NOW, "", "", None)
    )

    await handler(job)


@pytest.mark.asyncio
async def test_completed_notify_replays_notification_without_agent_execution() -> None:
    handler, job, notifications = _handler(AgentDelivery.NOTIFY)
    runs = handler._runs
    assert isinstance(runs, Runs)
    runs.run.status = AgentRunStatus.COMPLETED
    runs.run.final_content = "持久化结果"
    runs.run.final_delivery = AgentDelivery.NOTIFY
    runs.failure = AssertionError("completed run must not execute")

    await handler(job)

    assert notifications.requests[0].content == "持久化结果"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure_class", "error_type"),
    [
        ("TimeoutOrNetwork", RetryableJobError),
        ("RateLimit", RetryableJobError),
        ("ProviderUnavailable", RetryableJobError),
        ("InvalidOutput", PermanentJobError),
        ("ContextBudgetExceeded", PermanentJobError),
    ],
)
async def test_model_failure_preserves_retry_taxonomy(
    failure_class: str, error_type: type[Exception]
) -> None:
    handler, job, notifications = _handler(AgentDelivery.HOLD, failure=ModelFailure(failure_class))

    with pytest.raises(error_type, match=failure_class):
        await handler(job)
    assert notifications.requests == []


@pytest.mark.asyncio
async def test_notification_persistence_failure_is_retryable() -> None:
    handler, job, _ = _handler(AgentDelivery.NOTIFY)

    class FailingNotifications:
        async def schedule_agent_mail_result(self, request: AgentMailResultRequest) -> None:
            del request
            raise RuntimeError("database unavailable")

    handler._notifications = FailingNotifications()
    with pytest.raises(RetryableJobError, match="AgentNotificationPersistenceFailed"):
        await handler(job)
