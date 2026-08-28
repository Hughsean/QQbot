import asyncio
import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import SecretStr

from qq_time_agent.adapters.inbound.qq.gateway import (
    InteractionProbeResult,
    OfficialQqGateway,
    QqMessageProcessor,
    _BotpyClient,
    _delivery_id,
    _parse_timestamp,
    _qq_assets,
    _summarize_raw_event,
)
from qq_time_agent.bootstrap.config_models import OwnerConfig, QqConfig
from qq_time_agent.contracts.source import SourceAssetDescriptor, SourceEnvelope, TrustLevel
from qq_time_agent.modules.agent.contracts import AgentResponseProtocolError


@dataclass
class FixedClock:
    value: datetime

    def now(self) -> datetime:
        return self.value


@dataclass
class RecordingIngress:
    received: list[tuple[SourceEnvelope, str]] = field(default_factory=list)

    async def receive(self, envelope: SourceEnvelope, content: str) -> str:
        self.received.append((envelope, content))
        return "accepted"


@dataclass
class RecordingAssetIngress:
    received: list[tuple[SourceEnvelope, str, tuple[SourceAssetDescriptor, ...]]] = field(
        default_factory=list
    )

    async def receive(
        self,
        envelope: SourceEnvelope,
        content: str,
        assets: tuple[SourceAssetDescriptor, ...] = (),
    ) -> str:
        self.received.append((envelope, content, assets))
        return "accepted"


@dataclass
class FailingIngress:
    error: Exception

    async def receive(self, envelope: SourceEnvelope, content: str) -> str:
        raise self.error


@dataclass
class CallbackMessage:
    author_openid: str
    content: str | None
    attachments: object = None
    id: str = "message-1"
    timestamp: str = "2026-08-13T00:00:00Z"
    replies: list[str] = field(default_factory=list)

    @property
    def author(self) -> SimpleNamespace:
        return SimpleNamespace(user_openid=self.author_openid)

    async def reply(self, *, content: str) -> None:
        self.replies.append(content)


@pytest.mark.asyncio
async def test_official_image_descriptor_reaches_owner_ingress() -> None:
    ingress = RecordingAssetIngress()
    now = datetime(2026, 8, 13, tzinfo=UTC)
    processor = QqMessageProcessor(OwnerConfig(SecretStr("owner")), ingress, FixedClock(now))
    descriptor = SourceAssetDescriptor(
        "media-1",
        "https://gchat.qpic.cn/image/opaque",
        "screenshot.png",
        "image/png",
        128,
    )
    assert (
        await processor.process("owner", "message-1", "caption", now, (descriptor,)) == "accepted"
    )
    assert ingress.received[0][2] == (descriptor,)
    assert ingress.received[0][0].trust_level is TrustLevel.T1


def test_raw_event_summary_excludes_sensitive_scalar_values() -> None:
    payload = {
        "id": "event-secret-id",
        "d": {
            "id": "message-secret-id",
            "content": "绝密聊天正文",
            "author": {"user_openid": "owner-secret-openid"},
            "attachments": [
                {
                    "id": "asset-secret-id",
                    "url": "https://secret.example/asset?token=hidden",
                    "filename": "private-name.png",
                    "content_type": "image/png",
                    "size": 128,
                    "width": 640,
                    "height": 480,
                }
            ],
        },
    }
    summary = _summarize_raw_event(payload)
    rendered = repr(summary)
    assert "content:str" in rendered
    assert "author.user_openid:str" in rendered
    assert "attachments:list" in rendered
    assert "image/png" in rendered and "128" in rendered and "640" in rendered
    for secret in (
        "event-secret-id",
        "message-secret-id",
        "绝密聊天正文",
        "owner-secret-openid",
        "asset-secret-id",
        "https://secret.example",
        "private-name.png",
    ):
        assert secret not in rendered


@pytest.mark.asyncio
async def test_raw_event_diagnostic_wraps_parser_once_and_preserves_dispatch(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    parsed: list[object] = []

    def original(payload: object) -> object:
        parsed.append(payload)
        return payload

    async def fake_login(client: Any, token: object) -> None:
        del token
        client._connection = SimpleNamespace(parser={"c2c_message_create": original})

    monkeypatch.setattr("botpy.Client._bot_login", fake_login)
    processor = QqMessageProcessor(
        OwnerConfig(SecretStr("owner")),
        RecordingIngress(),
        FixedClock(datetime(2026, 8, 13, tzinfo=UTC)),
    )
    client = _BotpyClient(processor, True, diagnostic_raw_event_once=True)

    with caplog.at_level("INFO"):
        await client._bot_login(object())
        parser = client._connection.parser["c2c_message_create"]
        first = {"d": {"content": "first-secret"}}
        second = {"d": {"content": "second-secret"}}
        assert parser(first) is first
        assert parser(second) is second

    diagnostic_records = [record for record in caplog.records if hasattr(record, "event_structure")]
    assert len(diagnostic_records) == 1
    assert parsed == [first, second]
    assert client._diagnostic_raw_event_once is False
    rendered = caplog.text
    assert "first-secret" not in rendered
    assert "second-secret" not in rendered


@pytest.mark.asyncio
async def test_raw_event_diagnostic_disabled_does_not_wrap_parser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def original(payload: object) -> object:
        return payload

    async def fake_login(client: Any, token: object) -> None:
        del token
        client._connection = SimpleNamespace(parser={"c2c_message_create": original})

    monkeypatch.setattr("botpy.Client._bot_login", fake_login)
    processor = QqMessageProcessor(
        OwnerConfig(SecretStr("owner")),
        RecordingIngress(),
        FixedClock(datetime(2026, 8, 13, tzinfo=UTC)),
    )
    client = _BotpyClient(processor, True)
    await client._bot_login(object())
    assert client._connection.parser["c2c_message_create"] is original


def test_raw_event_summary_handles_missing_or_malformed_data() -> None:
    assert _summarize_raw_event(None)["event_type"] == "dict"
    assert _summarize_raw_event({"d": "not-a-mapping"}) == {
        "event_type": "str",
        "fields": (),
        "attachments": (),
    }


def test_official_attachment_mapping_accepts_url_only_c2c_image() -> None:
    locator = "https://gchat.qpic.cn/image/opaque"
    assets, unsupported = _qq_assets([SimpleNamespace(url=locator)])
    assert not unsupported
    assert assets == (
        SourceAssetDescriptor(
            hashlib.sha256(locator.encode()).hexdigest(),
            locator,
            None,
            "image/unknown",
            None,
        ),
    )


def test_official_attachment_mapping_rejects_non_image_and_incomplete_values() -> None:
    image = SimpleNamespace(
        id="media-1",
        url="https://gchat.qpic.cn/image/opaque",
        filename="image.png",
        content_type="image/png",
        size=128,
    )
    assets, unsupported = _qq_assets([image])
    assert not unsupported and assets[0].provider_asset_id == "media-1"
    non_image = SimpleNamespace(
        id="forward-1",
        url="https://gchat.qpic.cn/forward/opaque",
        filename="forward.json",
        content_type="application/qq-forward",
        size=128,
    )
    assert _qq_assets([non_image]) == ((), True)


@pytest.mark.asyncio
async def test_callback_rejects_non_owner_before_attachment_capability_reply() -> None:
    ingress = RecordingAssetIngress()
    processor = QqMessageProcessor(
        OwnerConfig(SecretStr("owner")),
        ingress,
        FixedClock(datetime(2026, 8, 13, tzinfo=UTC)),
    )
    client = _BotpyClient(processor, True)
    message = CallbackMessage(
        "intruder",
        "",
        [SimpleNamespace(content_type="application/qq-forward")],
    )

    await client.on_c2c_message_create(message)  # type: ignore[arg-type]

    assert message.replies == []
    assert ingress.received == []


@pytest.mark.asyncio
async def test_callback_treats_none_attachments_as_ordinary_text() -> None:
    ingress = RecordingAssetIngress()
    processor = QqMessageProcessor(
        OwnerConfig(SecretStr("owner")),
        ingress,
        FixedClock(datetime(2026, 8, 13, tzinfo=UTC)),
    )
    client = _BotpyClient(processor, True)
    message = CallbackMessage("owner", "你好", None)

    await client.on_c2c_message_create(message)  # type: ignore[arg-type]

    assert ingress.received[0][1:] == ("你好", ())
    assert message.replies == ["accepted"]


@pytest.mark.asyncio
async def test_callback_keeps_valid_image_when_other_attachment_is_unsupported() -> None:
    ingress = RecordingAssetIngress()
    processor = QqMessageProcessor(
        OwnerConfig(SecretStr("owner")),
        ingress,
        FixedClock(datetime(2026, 8, 13, tzinfo=UTC)),
    )
    client = _BotpyClient(processor, True)
    image = SimpleNamespace(
        id="media-1",
        url="https://gchat.qpic.cn/image/opaque",
        filename="image.png",
        content_type="image/png",
        size=128,
    )
    unsupported = SimpleNamespace(
        id="forward-1",
        url="https://gchat.qpic.cn/forward/opaque",
        content_type="application/qq-forward",
    )
    message = CallbackMessage("owner", "图片说明", [unsupported, image])

    await client.on_c2c_message_create(message)  # type: ignore[arg-type]

    assert ingress.received[0][1] == "图片说明"
    assert [asset.provider_asset_id for asset in ingress.received[0][2]] == ["media-1"]
    assert message.replies == ["accepted\n部分附件因官方 QQ 接口未提供读取能力而未处理。"]


@pytest.mark.asyncio
async def test_callback_rejects_unsupported_only_input_without_ingress() -> None:
    ingress = RecordingAssetIngress()
    processor = QqMessageProcessor(
        OwnerConfig(SecretStr("owner")),
        ingress,
        FixedClock(datetime(2026, 8, 13, tzinfo=UTC)),
    )
    client = _BotpyClient(processor, True)
    message = CallbackMessage(
        "owner",
        "",
        [SimpleNamespace(url="opaque", content_type="application/qq-forward")],
    )

    await client.on_c2c_message_create(message)  # type: ignore[arg-type]

    assert ingress.received == []
    assert message.replies == [
        "小智\N{FULLWIDTH COLON}当前官方 QQ 接口未提供此附件类型或合并转发的读取权限。"
    ]


@pytest.mark.asyncio
async def test_callback_accepts_image_without_caption() -> None:
    ingress = RecordingAssetIngress()
    processor = QqMessageProcessor(
        OwnerConfig(SecretStr("owner")),
        ingress,
        FixedClock(datetime(2026, 8, 13, tzinfo=UTC)),
    )
    client = _BotpyClient(processor, True)
    message = CallbackMessage(
        "owner",
        None,
        [SimpleNamespace(id="media-1", url="opaque", content_type="image/png")],
    )

    await client.on_c2c_message_create(message)  # type: ignore[arg-type]

    assert ingress.received[0][1] == ""
    assert ingress.received[0][2][0].provider_asset_id == "media-1"
    assert message.replies == ["accepted"]


@pytest.mark.asyncio
async def test_callback_processes_text_when_only_attachment_is_unsupported() -> None:
    ingress = RecordingAssetIngress()
    processor = QqMessageProcessor(
        OwnerConfig(SecretStr("owner")),
        ingress,
        FixedClock(datetime(2026, 8, 13, tzinfo=UTC)),
    )
    client = _BotpyClient(processor, True)
    message = CallbackMessage(
        "owner",
        "仍然处理这段文字",
        [SimpleNamespace(url="opaque", content_type="application/qq-forward")],
    )

    await client.on_c2c_message_create(message)  # type: ignore[arg-type]

    assert ingress.received[0][1:] == ("仍然处理这段文字", ())
    assert message.replies == ["accepted\n部分附件因官方 QQ 接口未提供读取能力而未处理。"]


@pytest.mark.asyncio
async def test_non_owner_is_rejected_before_ingress() -> None:
    ingress = RecordingIngress()
    now = datetime(2026, 8, 13, tzinfo=UTC)
    processor = QqMessageProcessor(OwnerConfig(SecretStr("owner")), ingress, FixedClock(now))
    reply = await processor.process("intruder", "m1", "hello", now)
    assert reply is None
    assert ingress.received == []


@pytest.mark.asyncio
async def test_owner_message_becomes_t1_provider_neutral_envelope() -> None:
    now = datetime(2026, 8, 13, 12, tzinfo=UTC)
    ingress = RecordingIngress()
    processor = QqMessageProcessor(OwnerConfig(SecretStr("owner")), ingress, FixedClock(now))
    reply = await processor.process("owner", "m1", "hello", now)
    envelope, content = ingress.received[0]
    assert reply == "accepted"
    assert content == "hello"
    assert envelope.trust_level is TrustLevel.T1
    assert envelope.external_id == "m1"
    assert envelope.content_hash.startswith("sha256:")


@pytest.mark.asyncio
async def test_owner_command_errors_are_safe_and_provider_details_are_hidden() -> None:
    now = datetime(2026, 8, 13, tzinfo=UTC)
    expected = QqMessageProcessor(
        OwnerConfig(SecretStr("owner")), FailingIngress(ValueError("bad command")), FixedClock(now)
    )
    assert await expected.process("owner", "m1", "bad", now) == (
        "小智\N{FULLWIDTH COLON}无法执行: bad command"
    )
    unexpected = QqMessageProcessor(
        OwnerConfig(SecretStr("owner")),
        FailingIngress(RuntimeError("provider secret detail")),
        FixedClock(now),
    )
    reply = await unexpected.process("owner", "m2", "bad", now)
    assert reply == "小智\N{FULLWIDTH COLON}处理失败, 请稍后重试。"
    assert "provider secret" not in reply


@pytest.mark.asyncio
async def test_agent_protocol_error_has_a_stable_user_facing_reply() -> None:
    now = datetime(2026, 8, 13, tzinfo=UTC)
    processor = QqMessageProcessor(
        OwnerConfig(SecretStr("owner")),
        FailingIngress(AgentResponseProtocolError("raw provider detail")),
        FixedClock(now),
    )
    reply = await processor.process("owner", "m1", "你好", now)
    assert reply == "小智\N{FULLWIDTH COLON}模型回复格式异常, 请稍后重试."
    assert "provider" not in reply


class StopReconnect(RuntimeError):
    pass


@dataclass
class FailingClient:
    starts: int = 0

    async def start(self, app_id: str, secret: str) -> None:
        self.starts += 1
        raise ConnectionError("synthetic disconnect")

    async def close(self) -> None:
        return None

    async def send_active(self, openid: str, content: str) -> str:
        return "delivery-id"

    async def wait_ready(self, timeout_seconds: float) -> None:
        return None


@dataclass
class ReadyClient:
    stopped: asyncio.Event = field(default_factory=asyncio.Event)
    closed: bool = False

    async def start(self, app_id: str, secret: str) -> None:
        await self.stopped.wait()

    async def close(self) -> None:
        self.closed = True

    async def send_active(self, openid: str, content: str) -> str:
        return "delivery-id"

    async def wait_ready(self, timeout_seconds: float) -> None:
        return None


@pytest.mark.asyncio
async def test_gateway_supervisor_reconnects_after_disconnect() -> None:
    clients: list[FailingClient] = []

    def factory(_: QqMessageProcessor) -> FailingClient:
        client = FailingClient()
        clients.append(client)
        return client

    backoffs: list[float] = []

    async def stop_after_backoff(value: float) -> None:
        backoffs.append(value)
        if len(backoffs) == 2:
            raise StopReconnect

    gateway = OfficialQqGateway(
        QqConfig(SecretStr("app"), SecretStr("secret"), True),
        OwnerConfig(SecretStr("owner")),
        RecordingIngress(),
        FixedClock(datetime(2026, 8, 13, tzinfo=UTC)),
        client_factory=factory,
        sleep=stop_after_backoff,
    )
    with pytest.raises(StopReconnect):
        await gateway.run_forever()
    assert len(clients) == 2
    assert [client.starts for client in clients] == [1, 1]
    assert backoffs == [2.0, 4.0]


@pytest.mark.asyncio
async def test_gateway_ready_send_and_cancel_close_client() -> None:
    client = ReadyClient()
    gateway = OfficialQqGateway(
        QqConfig(SecretStr("app"), SecretStr("secret"), True),
        OwnerConfig(SecretStr("owner")),
        RecordingIngress(),
        FixedClock(datetime(2026, 8, 13, tzinfo=UTC)),
        client_factory=lambda _: client,
    )
    running = asyncio.create_task(gateway.run_forever())
    await gateway.wait_ready()
    assert await gateway.send_active("hello") == "delivery-id"
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    assert client.closed


@pytest.mark.asyncio
async def test_interaction_probe_sends_keyboard_acknowledges_owner_and_confirms() -> None:
    processor = QqMessageProcessor(
        OwnerConfig(SecretStr("owner")),
        RecordingIngress(),
        FixedClock(datetime(2026, 8, 13, tzinfo=UTC)),
    )
    client = _BotpyClient(processor, True, interaction_probe_enabled=True)
    calls: list[tuple[str, dict[str, object]]] = []
    acked: list[tuple[str, int]] = []

    class Api:
        async def post_c2c_message(self, **kwargs: object) -> dict[str, str]:
            calls.append(("message", kwargs))
            return {"id": "probe-message"}

        async def on_interaction_result(self, interaction_id: str, code: int) -> None:
            acked.append((interaction_id, code))

    client.api = Api()
    pending = asyncio.create_task(client.probe_interaction("owner", 1))
    await asyncio.sleep(0)
    payload = calls[0][1]
    keyboard = payload["keyboard"]
    assert payload["msg_type"] == 2
    assert payload["markdown"] == {"content": "QQ 交互能力测试\n请点击任意测试按钮。"}
    assert isinstance(keyboard, dict)
    button = keyboard["content"]["rows"][0]["buttons"][0]
    interaction = SimpleNamespace(
        id="interaction-1",
        user_openid="owner",
        data=SimpleNamespace(
            resolved=SimpleNamespace(button_id=button["id"], button_data=button["action"]["data"])
        ),
    )
    await client.on_interaction_create(interaction)
    result = await pending

    assert result == InteractionProbeResult("interaction-1", "qq-time-probe-a", True)
    assert acked == [("interaction-1", 0)]
    assert calls[-1] == ("message", {"openid": "owner", "content": "测试按钮已收到。"})


@pytest.mark.asyncio
async def test_interaction_probe_ignores_non_owner_without_ack() -> None:
    processor = QqMessageProcessor(
        OwnerConfig(SecretStr("owner")),
        RecordingIngress(),
        FixedClock(datetime(2026, 8, 13, tzinfo=UTC)),
    )
    client = _BotpyClient(processor, True, interaction_probe_enabled=True)
    calls: list[dict[str, object]] = []

    async def post_c2c_message(**kwargs: object) -> None:
        calls.append(kwargs)

    async def on_interaction_result(interaction_id: str, code: int) -> None:
        del interaction_id, code
        pytest.fail("unexpected ack")

    client.api = SimpleNamespace(
        post_c2c_message=post_c2c_message,
        on_interaction_result=on_interaction_result,
    )
    pending = asyncio.create_task(client.probe_interaction("owner", 0.01))
    await asyncio.sleep(0)
    await client.on_interaction_create(
        SimpleNamespace(
            id="interaction-1",
            user_openid="other",
            data=SimpleNamespace(
                resolved=SimpleNamespace(button_id="qq-time-probe-a", button_data="wrong")
            ),
        )
    )
    with pytest.raises(asyncio.TimeoutError):
        await pending
    assert len(calls) == 1


def test_qq_provider_response_mapping_is_contained() -> None:
    assert _delivery_id({"id": "one"}) == "one"
    assert _delivery_id({"msg_id": "two"}) == "two"
    with pytest.raises(RuntimeError, match="omitted"):
        _delivery_id({})


def test_qq_timestamp_parser_requires_rfc3339_timezone() -> None:
    assert _parse_timestamp("2026-08-13T10:00:00Z").tzinfo is not None
    with pytest.raises(ValueError, match="RFC3339"):
        _parse_timestamp("not-a-time")
