import asyncio
import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from qq_time_agent.adapters.inbound.qq.gateway import (
    OfficialQqGateway,
    QqMessageProcessor,
    _delivery_id,
    _parse_timestamp,
    _qq_assets,
)
from qq_time_agent.bootstrap.config_models import OwnerConfig, QqConfig
from qq_time_agent.contracts.source import SourceAssetDescriptor, SourceEnvelope, TrustLevel


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
    assert await expected.process("owner", "m1", "bad", now) == "无法执行: bad command"
    unexpected = QqMessageProcessor(
        OwnerConfig(SecretStr("owner")),
        FailingIngress(RuntimeError("provider secret detail")),
        FixedClock(now),
    )
    reply = await unexpected.process("owner", "m2", "bad", now)
    assert reply == "处理失败, 请稍后重试。"
    assert "provider secret" not in reply


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


def test_qq_provider_response_mapping_is_contained() -> None:
    assert _delivery_id({"id": "one"}) == "one"
    assert _delivery_id({"msg_id": "two"}) == "two"
    with pytest.raises(RuntimeError, match="omitted"):
        _delivery_id({})


def test_qq_timestamp_parser_requires_rfc3339_timezone() -> None:
    assert _parse_timestamp("2026-08-13T10:00:00Z").tzinfo is not None
    with pytest.raises(ValueError, match="RFC3339"):
        _parse_timestamp("not-a-time")
