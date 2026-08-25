import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from qq_time_agent.adapters.inbound.qq.commands import QqCommandRouter
from qq_time_agent.contracts.jobs import JobRequest
from qq_time_agent.contracts.source import (
    IngressType,
    SourceAssetDescriptor,
    SourceEnvelope,
    SourceSender,
    SourceType,
    TrustLevel,
)
from qq_time_agent.modules.ai_gateway.contracts import AnswerCitation, GroundedAnswer
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
    created: bool = True

    async def ingest_qq(self, envelope: SourceEnvelope, content: str) -> IngestResult:
        self.envelopes.append(envelope)
        return IngestResult(self.inbox_item_id, self.created, "RECEIVED")

    async def mark_normalized(self, inbox_item_id: UUID) -> None:
        self.normalized.append(inbox_item_id)

    async def mark_understood(self, inbox_item_id: UUID) -> None:
        return None

    async def mark_needs_review(self, inbox_item_id: UUID) -> None:
        return None

    async def mark_ignored(self, inbox_item_id: UUID) -> None:
        return None

    async def mark_proposed(self, inbox_item_id: UUID) -> None:
        return None

    async def mark_completed(self, inbox_item_id: UUID) -> None:
        return None


@dataclass
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
        return NormalizedContentView(inbox_item_id, subject, body_text, source_hash, "v1")


@dataclass
class Queue:
    values: list[JobRequest] = field(default_factory=list)

    async def enqueue(self, request: JobRequest) -> UUID:
        self.values.append(request)
        return uuid4()


@dataclass
class ForbiddenScheduling:
    calls: int = 0

    def __getattr__(self, name: str) -> object:
        async def fail(*args: object, **kwargs: object) -> object:
            self.calls += 1
            raise AssertionError("forwarded content reached command side effect")

        return fail


@dataclass
class Discovery:
    values: list[tuple[UUID, tuple[SourceAssetDescriptor, ...]]] = field(default_factory=list)

    async def discover(
        self,
        inbox_item_id: UUID,
        attachments: tuple[SourceAssetDescriptor, ...],
        now: datetime,
    ) -> tuple[UUID, ...]:
        del now
        self.values.append((inbox_item_id, attachments))
        return tuple(uuid4() for _ in attachments)


@dataclass
class Forbidden:
    def __getattr__(self, name: str) -> object:
        async def fail(*args: object, **kwargs: object) -> object:
            raise AssertionError("unexpected side effect")

        return fail


@dataclass
class Rag:
    async def answer(self, question: str) -> GroundedAnswer:
        return GroundedAnswer(
            f"答案:{question}",
            (AnswerCitation("owner-note:1", "OWNER_NOTE", Clock().now()),),
            False,
        )

    async def answer_general(self, question: str) -> GroundedAnswer:
        return GroundedAnswer(f"通用:{question}", (), True)


@dataclass
class Agent:
    async def run(self, owner_id: str, message: str, context: str = "") -> object:
        assert owner_id == "owner" and message
        del context
        return type("Final", (), {"content": "Agent已处理"})()


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
async def test_forwarded_confirmation_text_is_t2_data_not_command() -> None:
    inbox = Inbox()
    scheduling = ForbiddenScheduling()
    queue = Queue()
    router = QqCommandRouter(
        inbox,
        inbox,
        Normalization(),
        scheduling,  # type: ignore[arg-type]
        Forbidden(),  # type: ignore[arg-type]
        Forbidden(),  # type: ignore[arg-type]
        Forbidden(),  # type: ignore[arg-type]
        Forbidden(),  # type: ignore[arg-type]
        Forbidden(),  # type: ignore[arg-type]
        queue,  # type: ignore[arg-type]
        Clock(),
        15,
    )
    reply = await router.receive(_envelope("转发: 确认 deadbeef-1"), "转发: 确认 deadbeef-1")
    assert "已接收转发文本" in reply
    assert scheduling.calls == 0
    assert inbox.envelopes[0].source_type is SourceType.QQ_FORWARD
    assert inbox.envelopes[0].trust_level is TrustLevel.T2
    assert queue.values[0].payload.keys() == {"inbox_item_id"}


@pytest.mark.asyncio
async def test_plain_direct_input_is_t1_and_enqueued_once() -> None:
    inbox = Inbox()
    queue = Queue()
    content = "下周找两小时写报告"
    router = QqCommandRouter(
        inbox,
        inbox,
        Normalization(),
        ForbiddenScheduling(),  # type: ignore[arg-type]
        Forbidden(),  # type: ignore[arg-type]
        Forbidden(),  # type: ignore[arg-type]
        Forbidden(),  # type: ignore[arg-type]
        Forbidden(),  # type: ignore[arg-type]
        Forbidden(),  # type: ignore[arg-type]
        queue,  # type: ignore[arg-type]
        Clock(),
        15,
    )
    await router.receive(_envelope(content), content)
    assert inbox.envelopes[0].trust_level is TrustLevel.T1
    assert queue.values[0].idempotency_key.startswith("understanding:")


@pytest.mark.asyncio
async def test_owner_note_is_t2_index_source_without_understanding_job() -> None:
    inbox = Inbox()
    queue = Queue()
    content = "笔记: 星河项目联系人是林澄"
    router = QqCommandRouter(
        inbox,
        inbox,
        Normalization(),
        ForbiddenScheduling(),  # type: ignore[arg-type]
        Forbidden(),  # type: ignore[arg-type]
        Forbidden(),  # type: ignore[arg-type]
        Forbidden(),  # type: ignore[arg-type]
        Forbidden(),  # type: ignore[arg-type]
        Forbidden(),  # type: ignore[arg-type]
        queue,  # type: ignore[arg-type]
        Clock(),
        15,
    )
    reply = await router.receive(_envelope(content), content)
    assert "已保存主人笔记" in reply
    assert inbox.envelopes[0].source_type is SourceType.OWNER_NOTE
    assert inbox.envelopes[0].trust_level is TrustLevel.T2
    assert inbox.normalized
    assert queue.values == []


@pytest.mark.asyncio
async def test_query_uses_read_only_rag_and_renders_source() -> None:
    inbox = Inbox()
    queue = Queue()
    router = QqCommandRouter(
        inbox,
        inbox,
        Normalization(),
        ForbiddenScheduling(),  # type: ignore[arg-type]
        Forbidden(),  # type: ignore[arg-type]
        Forbidden(),  # type: ignore[arg-type]
        Forbidden(),  # type: ignore[arg-type]
        Forbidden(),  # type: ignore[arg-type]
        Forbidden(),  # type: ignore[arg-type]
        queue,  # type: ignore[arg-type]
        Clock(),
        15,
        Rag(),
    )
    reply = await router.receive(_envelope("查询: 星河联系人"), "查询: 星河联系人")
    assert "答案:星河联系人" in reply and "owner-note:1" in reply
    assert inbox.envelopes == [] and queue.values == []


@pytest.mark.asyncio
async def test_plain_owner_message_gets_immediate_read_only_reply() -> None:
    inbox = Inbox()
    queue = Queue()
    router = QqCommandRouter(
        inbox,
        inbox,
        Normalization(),
        ForbiddenScheduling(),  # type: ignore[arg-type]
        Forbidden(),  # type: ignore[arg-type]
        Forbidden(),  # type: ignore[arg-type]
        Forbidden(),  # type: ignore[arg-type]
        Forbidden(),  # type: ignore[arg-type]
        Forbidden(),  # type: ignore[arg-type]
        queue,
        Clock(),
        15,
        general_answer=Rag(),
    )
    reply = await router.receive(_envelope("你好"), "你好")
    assert reply == "通用:你好"
    assert inbox.envelopes and queue.values


@pytest.mark.asyncio
async def test_agent_path_persists_direct_message_without_legacy_understanding_job() -> None:
    inbox = Inbox()
    queue = Queue()
    router = QqCommandRouter(
        inbox,
        inbox,
        Normalization(),
        ForbiddenScheduling(),  # type: ignore[arg-type]
        Forbidden(),  # type: ignore[arg-type]
        Forbidden(),  # type: ignore[arg-type]
        Forbidden(),  # type: ignore[arg-type]
        Forbidden(),  # type: ignore[arg-type]
        Forbidden(),  # type: ignore[arg-type]
        queue,
        Clock(),
        15,
        agent=Agent(),  # type: ignore[arg-type]
    )
    reply = await router.receive(_envelope("刚才那个任务改到明天"), "刚才那个任务改到明天")
    assert reply == "Agent已处理"
    assert queue.values == []


@pytest.mark.asyncio
async def test_media_caption_cannot_execute_command_and_discovers_asset() -> None:
    inbox = Inbox()
    queue = Queue()
    scheduling = ForbiddenScheduling()
    discovery = Discovery()
    router = QqCommandRouter(
        inbox,
        inbox,
        Normalization(),
        scheduling,  # type: ignore[arg-type]
        Forbidden(),  # type: ignore[arg-type]
        Forbidden(),  # type: ignore[arg-type]
        Forbidden(),  # type: ignore[arg-type]
        Forbidden(),  # type: ignore[arg-type]
        Forbidden(),  # type: ignore[arg-type]
        queue,  # type: ignore[arg-type]
        Clock(),
        15,
        asset_discovery=discovery,
    )
    descriptor = SourceAssetDescriptor(
        "media-1",
        "https://gchat.qpic.cn/image/opaque",
        "screenshot.png",
        "image/png",
        128,
    )
    reply = await router.receive(_envelope("确认 deadbeef-1"), "确认 deadbeef-1", (descriptor,))
    assert "已接收图片" in reply
    inbox.created = False
    duplicate_reply = await router.receive(
        _envelope("确认 deadbeef-1"), "确认 deadbeef-1", (descriptor,)
    )
    assert "已接收图片" in duplicate_reply
    assert scheduling.calls == 0
    assert [value[0] for value in discovery.values] == [inbox.inbox_item_id] * 2
    assert discovery.values[0][1] == discovery.values[1][1] == (descriptor,)
