import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from qq_time_agent.adapters.inbound.qq.gateway import OfficialQqGateway
from qq_time_agent.bootstrap.settings import load_runtime_config
from qq_time_agent.contracts.source import SourceEnvelope

pytestmark = [pytest.mark.sandbox, pytest.mark.asyncio]


@dataclass
class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 8, 13, tzinfo=UTC)


@dataclass
class RecordingIngress:
    received: asyncio.Event = field(default_factory=asyncio.Event)
    envelope: SourceEnvelope | None = None
    content: str | None = None

    async def receive(self, envelope: SourceEnvelope, content: str) -> str:
        self.envelope = envelope
        self.content = content
        self.received.set()
        return "QQ Time Agent sandbox ingress accepted"


async def test_official_qq_gateway_login_and_active_c2c_message() -> None:
    config = load_runtime_config()
    gateway = OfficialQqGateway(config.qq, config.owner, RecordingIngress(), FixedClock())
    running = asyncio.create_task(gateway.run_forever())
    try:
        await gateway.wait_ready(30)
        delivery_id = await gateway.send_active("QQ Time Agent 阶段 1 沙箱主动消息验证")
        assert delivery_id
    finally:
        running.cancel()
        with pytest.raises(asyncio.CancelledError):
            await running


async def test_official_qq_owner_c2c_receive_and_reply() -> None:
    config = load_runtime_config()
    ingress = RecordingIngress()
    gateway = OfficialQqGateway(config.qq, config.owner, ingress, FixedClock())
    running = asyncio.create_task(gateway.run_forever())
    try:
        await gateway.wait_ready(30)
        await gateway.send_active("请直接回复: 阶段1入站验证")
        await asyncio.wait_for(ingress.received.wait(), timeout=45)
        assert ingress.envelope is not None
        assert ingress.envelope.trust_level.value == "T1"
        assert ingress.content is not None and "阶段1入站验证" in ingress.content
    finally:
        running.cancel()
        with pytest.raises(asyncio.CancelledError):
            await running
