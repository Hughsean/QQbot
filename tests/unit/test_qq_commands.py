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
    AgentContextResult,
    AgentDelivery,
    AgentFinal,
    AgentRun,
    AgentRunExecution,
    AgentRunExecutionStatus,
    AgentRunStatus,
    AgentTurnClaim,
    AgentTurnSegmentRef,
    AgentTurnTicket,
    ConversationSnapshot,
)
from qq_time_agent.modules.ai_gateway.contracts import AgentMessage
from qq_time_agent.modules.inbox.contracts import InboxContentView, IngestResult
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

    async def get_content(self, inbox_item_id: UUID) -> InboxContentView | None:
        if inbox_item_id != self.inbox_item_id or not self.contents:
            return None
        return InboxContentView(
            inbox_item_id,
            "QQ 输入",
            self.contents[-1],
            None,
            "text/plain",
            datetime(2026, 8, 20, tzinfo=UTC),
            "qq:test",
            "hash",
            None,
        )


@dataclass
class Turns:
    claim: AgentTurnClaim | None = None
    completed: int = 0

    async def stage(self, **values: object) -> AgentTurnTicket:
        item_id = values["inbox_item_id"]
        occurred_at = values["occurred_at"]
        content_chars = values["content_chars"]
        assert (
            isinstance(item_id, UUID)
            and isinstance(occurred_at, datetime)
            and isinstance(content_chars, int)
        )
        turn_id = uuid4()
        self.claim = AgentTurnClaim(
            turn_id,
            1,
            "a" * 64,
            "owner",
            (
                AgentTurnSegmentRef(
                    item_id,
                    1,
                    str(values["source_type"]),
                    str(values["trust_level"]),
                    occurred_at,
                    None,
                    None,
                    content_chars,
                ),
            ),
        )
        return AgentTurnTicket(turn_id, 1, occurred_at)

    async def settle(self, ticket: AgentTurnTicket) -> AgentTurnClaim | None:
        assert self.claim is not None and ticket.turn_id == self.claim.turn_id
        return self.claim

    async def complete(self, claim: AgentTurnClaim) -> None:
        assert claim == self.claim
        self.completed += 1

    async def release(self, claim: AgentTurnClaim) -> None:
        del claim

    async def fail(self, claim: AgentTurnClaim, failure_class: str) -> None:
        del claim, failure_class


@dataclass
class SequencedInbox:
    ids: list[UUID] = field(default_factory=lambda: [uuid4(), uuid4()])
    texts: list[str] = field(default_factory=list)
    marked: list[UUID] = field(default_factory=list)

    async def ingest_qq(
        self, envelope: SourceEnvelope, content: str, *, has_assets: bool = False
    ) -> IngestResult:
        del envelope, has_assets
        self.texts.append(content)
        return IngestResult(self.ids[len(self.texts) - 1], True, "RECEIVED")

    async def mark_normalized(self, inbox_item_id: UUID) -> None:
        self.marked.append(inbox_item_id)

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

    async def get_content(self, inbox_item_id: UUID) -> InboxContentView | None:
        if inbox_item_id not in self.ids or len(self.texts) < len(self.ids):
            return None
        index = self.ids.index(inbox_item_id)
        return InboxContentView(
            inbox_item_id,
            "QQ 输入",
            self.texts[index],
            None,
            "text/plain",
            datetime(2026, 8, 20, tzinfo=UTC),
            "qq:test",
            "hash",
            None,
        )


@dataclass
class OutOfOrderTurns:
    """QQ 平台乱序投递:命令先到,证据后到且 occurred_at 更早;证据回调领批。"""

    claim: AgentTurnClaim | None = None
    completed: int = 0
    released: int = 0
    command_id: UUID | None = None
    evidence_id: UUID | None = None

    async def stage(self, **values: object) -> AgentTurnTicket:
        item_id = values["inbox_item_id"]
        occurred_at = values["occurred_at"]
        assert isinstance(item_id, UUID) and isinstance(occurred_at, datetime)
        if self.command_id is None:
            self.command_id = item_id
            return AgentTurnTicket(uuid4(), 1, occurred_at)
        self.evidence_id = item_id
        base = datetime(2026, 8, 20, tzinfo=UTC)
        self.claim = AgentTurnClaim(
            uuid4(),
            2,
            "a" * 64,
            "owner",
            (
                AgentTurnSegmentRef(
                    item_id, 2, "QQ_DIRECT", "T1", base - timedelta(seconds=1), None, None, 200
                ),
                AgentTurnSegmentRef(self.command_id, 1, "QQ_DIRECT", "T1", base, None, None, 10),
            ),
        )
        return AgentTurnTicket(self.claim.turn_id, 2, occurred_at)

    async def settle(self, ticket: AgentTurnTicket) -> AgentTurnClaim | None:
        if self.claim is not None and ticket.generation == 2:
            return self.claim
        return None

    async def complete(self, claim: AgentTurnClaim) -> None:
        del claim
        self.completed += 1

    async def release(self, claim: AgentTurnClaim) -> None:
        del claim
        self.released += 1

    async def fail(self, claim: AgentTurnClaim, failure_class: str) -> None:
        del claim, failure_class
        self.released += 1


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
    snapshot: ConversationSnapshot | None = None
    failures: list[str] = field(default_factory=list)

    async def ensure_run(
        self,
        inbox_item_id: UUID,
        user_id: str,
        source_type: str,
        conversation_key: str | None = None,
        event_key: str | None = None,
        occurred_at: datetime | None = None,
        message: str | None = None,
        source_refs: tuple[str, ...] = (),
    ) -> AgentRun:
        del source_refs
        assert user_id == "owner" and source_type == "QQ_DIRECT" and event_key is None
        assert conversation_key is not None and (
            conversation_key == "owner" or conversation_key.startswith("qq-turn:")
        )
        assert occurred_at is not None
        assert message is not None and message.strip()
        self.ensured.append(inbox_item_id)
        run = AgentRun(self.run_id, inbox_item_id, user_id, source_type, AgentRunStatus.PENDING, 0)
        if self.snapshot is not None:
            run.conversation_id = self.snapshot.scope_id
            run.context_revision = self.snapshot.revision
            run.context_max_sequence = self.snapshot.max_sequence
            run.context_hash = self.snapshot.context_hash
        return run

    async def get(self, run_id: UUID) -> AgentRun | None:
        return None

    async def execute(
        self,
        run_id: UUID,
        message: str,
        context: str = "",
        timeline_messages: tuple[AgentMessage, ...] = (),
        snapshot: ConversationSnapshot | None = None,
    ) -> AgentFinal:
        del timeline_messages
        assert snapshot == self.snapshot
        self.executed.append((run_id, message, context))
        return AgentFinal("Agent已处理", AgentDelivery.HOLD)

    async def fail_before_execution(self, run_id: UUID, failure_class: str) -> None:
        assert run_id == self.run_id
        self.failures.append(failure_class)


class Context:
    async def build(self, *args: object, **kwargs: object) -> str:
        del args, kwargs
        return "历史上下文"

    async def assemble(self, *args: object, **kwargs: object) -> AgentContextResult:
        del args
        return AgentContextResult("历史上下文", snapshot=kwargs.get("snapshot"))


class FailingContext(Context):
    async def assemble(self, *args: object, **kwargs: object) -> AgentContextResult:
        del args, kwargs
        raise ValueError("invalid context")


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
async def test_direct_message_passes_persisted_snapshot_to_execution() -> None:
    inbox, queue, runs = Inbox(), Queue(), Runs()
    runs.snapshot = ConversationSnapshot("owner", uuid4(), 5, 5, "c" * 64)

    await _router(inbox, queue, runs).receive(_envelope("继续"), "继续")

    assert len(runs.executed) == 1


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
async def test_coalesced_path_schedules_recovery_and_executes_one_run() -> None:
    inbox, queue, runs, turns = Inbox(), Queue(), Runs(), Turns()
    router = QqCommandRouter(
        inbox,
        inbox,
        Normalization(),
        queue,
        Clock(),
        None,
        Context(),
        runs,
        turn_coordinator=turns,  # type: ignore[arg-type]
        inbox_content=inbox,
    )

    reply = await router.receive(_envelope("创建明天下午三点的日程"), "创建明天下午三点的日程")

    assert reply == "小智\N{FULLWIDTH COLON}Agent已处理"
    assert [item.kind for item in queue.values] == ["qq-turn", "agent-run"]
    assert len(runs.ensured) == len(runs.executed) == 1
    assert turns.completed == 1


@pytest.mark.asyncio
async def test_out_of_order_batch_replies_via_evidence_callback_with_command_anchor() -> None:
    """QQ 乱序投递回归:命令先到、证据后到且 occurred_at 更早;证据回调领批。

    2026-09-14 生产事故:相等守卫把"领批消息 ≠ 命令消息"误判为错乱,导致先回
    "处理失败"、再由 Worker 恢复路径兜底回复。正确语义:回调消息属于本批即合法,
    且 AgentRun 审计锚点固定为命令消息。
    """
    inbox = SequencedInbox()
    queue, runs, turns = Queue(), Runs(), OutOfOrderTurns()
    router = QqCommandRouter(
        inbox,
        inbox,
        Normalization(),
        queue,
        Clock(),
        None,
        Context(),
        runs,
        turn_coordinator=turns,  # type: ignore[arg-type]
        inbox_content=inbox,
    )

    first = await router.receive(_envelope("记录一下日程提醒"), "记录一下日程提醒")
    assert first is None
    assert turns.command_id == inbox.ids[0]

    notice = "【1】时间:9月16日(周三)下午2:30 【3】人员统计:请各支部填写名单表。" * 3
    second = await router.receive(_envelope(notice), notice)

    assert second == "小智\N{FULLWIDTH COLON}Agent已处理"
    assert runs.ensured == [turns.command_id]
    assert len(runs.executed) == 1
    assert turns.completed == 1
    assert turns.released == 0


@pytest.mark.asyncio
async def test_direct_context_failure_marks_pending_run_failed() -> None:
    inbox, queue, runs = Inbox(), Queue(), Runs()
    router = _router(inbox, queue, runs)
    router._agent_context = FailingContext()

    with pytest.raises(ValueError, match="invalid context"):
        await router.receive(_envelope("?"), "?")

    assert runs.failures == ["ValueError"]
    assert runs.executed == []


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
        async def execute(
            self,
            run_id: UUID,
            message: str,
            context: str = "",
            timeline_messages: tuple[AgentMessage, ...] = (),
            snapshot: ConversationSnapshot | None = None,
        ) -> AgentRunExecution:
            del run_id, message, context, timeline_messages, snapshot
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
            message: str | None = None,
            source_refs: tuple[str, ...] = (),
        ) -> AgentRun:
            del (
                user_id,
                source_type,
                conversation_key,
                event_key,
                occurred_at,
                message,
                source_refs,
            )
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

        async def execute(
            self,
            run_id: UUID,
            message: str,
            context: str = "",
            timeline_messages: tuple[AgentMessage, ...] = (),
            snapshot: ConversationSnapshot | None = None,
        ) -> AgentFinal:
            del run_id, message, context, timeline_messages, snapshot
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
