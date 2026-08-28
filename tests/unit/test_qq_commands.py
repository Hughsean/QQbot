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
    AgentRunExecution,
    AgentRunExecutionStatus,
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
    contents: list[str] = field(default_factory=list)
    has_assets: list[bool] = field(default_factory=list)
    normalized: list[UUID] = field(default_factory=list)
    inbox_item_id: UUID = field(default_factory=uuid4)

    async def ingest_qq(
        self, envelope: SourceEnvelope, content: str, *, has_assets: bool = False
    ) -> IngestResult:
        self.envelopes.append(envelope)
        self.contents.append(content)
        self.has_assets.append(has_assets)
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
    values: list[UUID]

    def __init__(self) -> None:
        self.values = []

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
        self.values.append(inbox_item_id)
        return NormalizedContentView(
            inbox_item_id, subject, body_text, source_hash, "v1", source_ref
        )


@dataclass
class Queue:
    values: list[JobRequest] = field(default_factory=list)
    failure: Exception | None = None

    async def enqueue(self, request: JobRequest) -> UUID:
        if self.failure is not None:
            raise self.failure
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
    assert reply == "小智\N{FULLWIDTH COLON}Agent已处理"
    assert len(inbox.envelopes) == len(runs.ensured) == len(runs.executed) == 1
    assert queue.values[0].kind == "agent-run"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("marker", "text"),
    [
        ("转发:", "确认 deadbeef-1"),
        ("转发\N{FULLWIDTH COLON}", "确认 deadbeef-1"),
        ("[聊天记录]", "确认 deadbeef-1"),
        ("[合并转发]", "确认 deadbeef-1"),
        ("【聊天记录】", "确认 deadbeef-1"),
        ("【合并转发】", "确认 deadbeef-1"),
        ("聊天记录:", "确认 deadbeef-1"),
        ("聊天记录\N{FULLWIDTH COLON}", "确认 deadbeef-1"),
    ],
)
async def test_all_forwarded_markers_are_indexed_without_agent_run(marker: str, text: str) -> None:
    inbox, queue, runs = Inbox(), Queue(), Runs()
    reply = await _router(inbox, queue, runs).receive(
        _envelope(f"  {marker}   {text}  "), f"  {marker}   {text}  "
    )
    assert "已接收转发文本" in reply
    assert inbox.envelopes[0].source_type is SourceType.QQ_FORWARD
    assert inbox.envelopes[0].ingress_type is IngressType.FORWARDED
    assert inbox.envelopes[0].trust_level is TrustLevel.T2
    assert inbox.contents == [text]
    assert runs.ensured == runs.executed == [] and queue.values == []


@pytest.mark.asyncio
async def test_forward_marker_in_middle_is_ordinary_direct_message() -> None:
    inbox, queue, runs = Inbox(), Queue(), Runs()
    content = "普通文本 [聊天记录] 确认"
    await _router(inbox, queue, runs).receive(_envelope(content), content)
    assert inbox.envelopes[0].source_type is SourceType.QQ_DIRECT
    assert len(runs.executed) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "marker", ["转发:", "转发\N{FULLWIDTH COLON}", "[聊天记录]", "【合并转发】"]
)
async def test_empty_forward_marker_is_rejected(marker: str) -> None:
    inbox, queue, runs = Inbox(), Queue(), Runs()
    with pytest.raises(ValueError, match="转发文本不能为空"):
        await _router(inbox, queue, runs).receive(_envelope(marker), marker)
    assert runs.ensured == runs.executed == []


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
async def test_duplicate_media_ingress_skips_asset_discovery_and_normalization() -> None:
    inbox, queue, runs, discovery = Inbox(), Queue(), Runs(), Discovery()
    descriptor = SourceAssetDescriptor(
        "media-1", "https://gchat.qpic.cn/image/opaque", None, "image/png", 128
    )
    router = _router(inbox, queue, runs, discovery)

    await router.receive(_envelope("caption"), "caption", (descriptor,))
    await router.receive(_envelope("caption"), "caption", (descriptor,))

    assert inbox.has_assets == [True, True]
    assert len(discovery.values) == 1
    assert len(inbox.normalized) == 1
    assert runs.ensured == []
    assert queue.values == []


@pytest.mark.asyncio
async def test_image_only_ingress_forwards_blank_caption_with_asset_flag() -> None:
    inbox, queue, runs, discovery = Inbox(), Queue(), Runs(), Discovery()
    descriptor = SourceAssetDescriptor(
        "media-1", "https://gchat.qpic.cn/image/opaque", None, "image/png", 128
    )

    await _router(inbox, queue, runs, discovery).receive(_envelope(""), "", (descriptor,))

    assert inbox.contents == [""]
    assert inbox.has_assets == [True]
    assert len(discovery.values) == 1
    assert runs.ensured == []


@pytest.mark.asyncio
async def test_recovery_enqueue_failure_does_not_block_immediate_agent_execution() -> None:
    inbox, queue, runs = Inbox(), Queue(), Runs()
    queue.failure = RuntimeError("queue unavailable")

    reply = await _router(inbox, queue, runs).receive(_envelope("请处理"), "请处理")

    assert reply == "小智\N{FULLWIDTH COLON}Agent已处理"
    assert len(runs.executed) == 1


@pytest.mark.asyncio
async def test_in_progress_result_is_explicit_when_recovery_enqueue_fails() -> None:
    class InProgressRuns(Runs):
        async def execute(self, run_id: UUID, message: str, context: str = "") -> AgentRunExecution:
            del run_id, message, context
            return AgentRunExecution(AgentRunExecutionStatus.IN_PROGRESS)

    inbox, queue, runs = Inbox(), Queue(failure=RuntimeError("queue unavailable")), InProgressRuns()

    reply = await _router(inbox, queue, runs).receive(_envelope("请处理"), "请处理")

    assert "自动恢复暂不可用" in reply


@pytest.mark.asyncio
async def test_media_caption_markers_do_not_enter_agent_path() -> None:
    inbox, queue, runs, discovery = Inbox(), Queue(), Runs(), Discovery()
    descriptor = SourceAssetDescriptor(
        "media-1", "https://gchat.qpic.cn/image/opaque", None, "image/png", 128
    )

    for content in ("", "确认", "笔记: 私密", "转发: 外部文本"):
        await _router(inbox, queue, runs, discovery).receive(
            _envelope(content), content, (descriptor,)
        )

    assert runs.ensured == runs.executed == []
    assert queue.values == []
    assert inbox.contents == ["", "确认", "笔记: 私密", "转发: 外部文本"]
    assert inbox.has_assets == [True, True, True, True]
    assert len(discovery.values) == 1


@pytest.mark.asyncio
async def test_completed_duplicate_reuses_persisted_agent_reply() -> None:
    class CompletedRuns(Runs):
        async def ensure_run(
            self,
            inbox_item_id: UUID,
            user_id: str,
            source_type: str,
            conversation_key: str | None = None,
            event_key: str | None = None,
            occurred_at: datetime | None = None,
        ) -> AgentRun:
            del user_id, source_type, conversation_key, event_key, occurred_at
            self.ensured.append(inbox_item_id)
            return AgentRun(
                self.run_id,
                inbox_item_id,
                "owner",
                "QQ_DIRECT",
                AgentRunStatus.COMPLETED,
                1,
                final_content="持久化答复",
                final_delivery=AgentDelivery.HOLD,
            )

        async def execute(self, run_id: UUID, message: str, context: str = "") -> AgentFinal:
            raise AssertionError("completed duplicate must not execute")

    inbox, queue, runs = Inbox(), Queue(), CompletedRuns()
    reply = await _router(inbox, queue, runs).receive(_envelope("重复消息"), "重复消息")

    assert reply == "小智\N{FULLWIDTH COLON}持久化答复"
    assert runs.ensured == [inbox.inbox_item_id]
    assert queue.values == []


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
    assert reply.startswith("小智\N{FULLWIDTH COLON}")
    assert discovery.values and runs.ensured == []
