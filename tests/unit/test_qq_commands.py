import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from qq_time_agent.adapters.inbound.qq.commands import QqCommandRouter
from qq_time_agent.contracts.jobs import JobLease, JobRequest, JobStatusView
from qq_time_agent.contracts.source import (
    IngressType,
    SourceAssetDescriptor,
    SourceEnvelope,
    SourceSender,
    SourceType,
    TrustLevel,
)
from qq_time_agent.modules.agent.contracts import (
    AgentDelivery,
    AgentFinal,
    AgentRun,
    AgentRunStatus,
)
from qq_time_agent.modules.inbox.contracts import IngestResult
from qq_time_agent.modules.normalization.contracts import NormalizedContentView


@dataclass
class Clock:
    def now(self) -> datetime:
        return datetime(2026, 8, 20, tzinfo=UTC)


@dataclass
class Inbox:
    envelopes: list[SourceEnvelope] = field(default_factory=list)
    normalized: list[UUID] = field(default_factory=list)
    inbox_item_id: UUID = field(default_factory=uuid4)

    async def ingest_qq(self, envelope: SourceEnvelope, content: str) -> IngestResult:
        del content
        self.envelopes.append(envelope)
        return IngestResult(self.inbox_item_id, len(self.envelopes) == 1, "RECEIVED")

    async def mark_normalized(self, inbox_item_id: UUID) -> None:
        self.normalized.append(inbox_item_id)

    async def mark_understood(self, inbox_item_id: UUID) -> None:
        del inbox_item_id

    async def mark_needs_review(self, inbox_item_id: UUID) -> None:
        del inbox_item_id

    async def mark_ignored(self, inbox_item_id: UUID) -> None:
        del inbox_item_id

    async def mark_proposed(self, inbox_item_id: UUID) -> None:
        del inbox_item_id

    async def mark_completed(self, inbox_item_id: UUID) -> None:
        del inbox_item_id


class Normalization:
    async def normalize(
        self,
        inbox_item_id: UUID,
        subject: str,
        body_text: str,
        body_html: str | None,
        source_hash: str,
        source_ref: str | None = None,
    ) -> NormalizedContentView:
        del body_html
        return NormalizedContentView(
            inbox_item_id, subject, body_text, source_hash, "v1", source_ref
        )


@dataclass
class Queue:
    values: list[JobRequest] = field(default_factory=list)

    async def enqueue(self, request: JobRequest) -> UUID:
        self.values.append(request)
        return uuid4()

    async def lease_due(
        self, now: datetime, worker_id: str, limit: int, lease_duration: timedelta
    ) -> list[JobLease]:
        del now, worker_id, limit, lease_duration
        return []

    async def complete(self, lease: JobLease, now: datetime) -> None:
        del lease, now

    async def fail(
        self, lease: JobLease, now: datetime, failure_class: str, retry_at: datetime | None
    ) -> None:
        del lease, now, failure_class, retry_at

    async def status(self, job_id: UUID) -> JobStatusView | None:
        del job_id
        return None


@dataclass
class Discovery:
    values: list[tuple[UUID, tuple[SourceAssetDescriptor, ...]]] = field(default_factory=list)

    async def discover(
        self, inbox_item_id: UUID, attachments: tuple[SourceAssetDescriptor, ...], now: datetime
    ) -> tuple[UUID, ...]:
        del now
        self.values.append((inbox_item_id, attachments))
        return ()


@dataclass
class Runs:
    run_id: UUID = field(default_factory=uuid4)
    ensured: list[UUID] = field(default_factory=list)
    executed: list[tuple[UUID, str, str]] = field(default_factory=list)

    async def ensure_run(
        self,
        inbox_item_id: UUID,
        user_id: str,
        source_type: str,
        conversation_key: str | None = None,
        event_key: str | None = None,
        occurred_at: datetime | None = None,
    ) -> AgentRun:
        assert user_id == "owner" and source_type == "QQ_DIRECT" and event_key is None
        assert conversation_key == "owner" and occurred_at is not None
        self.ensured.append(inbox_item_id)
        return AgentRun(self.run_id, inbox_item_id, user_id, source_type, AgentRunStatus.PENDING, 0)

    async def get(self, run_id: UUID) -> AgentRun | None:
        return None

    async def execute(self, run_id: UUID, message: str, context: str = "") -> AgentFinal:
        self.executed.append((run_id, message, context))
        return AgentFinal("Agent已处理", AgentDelivery.HOLD)


class Context:
    async def build(self, *args: object, **kwargs: object) -> str:
        del args, kwargs
        return "历史上下文"


def _router(
    inbox: Inbox, queue: Queue, runs: Runs, discovery: Discovery | None = None
) -> QqCommandRouter:
    return QqCommandRouter(
        inbox, inbox, Normalization(), queue, Clock(), discovery, Context(), runs
    )


def _envelope(content: str) -> SourceEnvelope:
    now = datetime(2026, 8, 20, tzinfo=UTC)
    return SourceEnvelope(
        SourceType.QQ_DIRECT,
        IngressType.DIRECT,
        "message-1",
        None,
        now,
        now,
        SourceSender("owner"),
        "qq:message-1",
        f"sha256:{hashlib.sha256(content.encode()).hexdigest()}",
        TrustLevel.T1,
        {"message_kind": "c2c"},
    )


@pytest.mark.asyncio
async def test_direct_message_uses_one_persistent_agent_run() -> None:
    inbox, queue, runs = Inbox(), Queue(), Runs()
    reply = await _router(inbox, queue, runs).receive(
        _envelope("刚才那个任务改到明天"), "刚才那个任务改到明天"
    )
    assert reply == "Agent已处理"
    assert len(inbox.envelopes) == len(runs.ensured) == len(runs.executed) == 1
    assert queue.values[0].kind == "agent-run"


@pytest.mark.asyncio
async def test_forwarded_content_is_t2_and_never_creates_agent_run() -> None:
    inbox, queue, runs = Inbox(), Queue(), Runs()
    reply = await _router(inbox, queue, runs).receive(
        _envelope("转发: 确认 deadbeef-1"), "转发: 确认 deadbeef-1"
    )
    assert "已接收转发文本" in reply
    assert inbox.envelopes[0].source_type is SourceType.QQ_FORWARD
    assert runs.ensured == [] and queue.values == []


@pytest.mark.asyncio
async def test_owner_note_is_t2_index_source_without_agent_run() -> None:
    inbox, queue, runs = Inbox(), Queue(), Runs()
    reply = await _router(inbox, queue, runs).receive(
        _envelope("笔记: 星河联系人"), "笔记: 星河联系人"
    )
    assert "已保存主人笔记" in reply
    assert inbox.envelopes[0].source_type is SourceType.OWNER_NOTE
    assert runs.ensured == [] and queue.values == []


@pytest.mark.asyncio
async def test_media_caption_stays_out_of_the_agent_command_path() -> None:
    inbox, queue, runs, discovery = Inbox(), Queue(), Runs(), Discovery()
    descriptor = SourceAssetDescriptor(
        "media-1", "https://gchat.qpic.cn/image/opaque", None, "image/png", 128
    )
    reply = await _router(inbox, queue, runs, discovery).receive(
        _envelope("确认"), "确认", (descriptor,)
    )
    assert "已接收图片" in reply
    assert discovery.values and runs.ensured == []
