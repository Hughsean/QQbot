import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from qq_time_agent.adapters.inbound.qq.gateway import OfficialQqGateway
from qq_time_agent.adapters.outbound.qq.media import OfficialQqMediaRoute
from qq_time_agent.bootstrap.settings import load_runtime_config
from qq_time_agent.contracts.source import SourceAssetDescriptor, SourceEnvelope, SourceType
from qq_time_agent.modules.inbox.application.asset_ports import SourceAssetContext
from qq_time_agent.modules.inbox.domain.assets import AssetKind, SourceAsset
from qq_time_agent.modules.normalization.contracts import NormalizableAssetKind
from qq_time_agent.modules.normalization.infrastructure.document_parser import DocumentAssetParser
from qq_time_agent.modules.normalization.infrastructure.icalendar_parser import IcalendarParser

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


@dataclass
class RecordingImageIngress:
    received: asyncio.Event = field(default_factory=asyncio.Event)
    assets: tuple[SourceAssetDescriptor, ...] = ()

    async def receive(
        self,
        envelope: SourceEnvelope,
        content: str,
        assets: tuple[SourceAssetDescriptor, ...] = (),
    ) -> str:
        del envelope, content
        if assets:
            self.assets = assets
            self.received.set()
        return "阶段14图片已接收"


async def test_official_qq_gateway_login_and_active_c2c_message() -> None:
    config = load_runtime_config()
    gateway = OfficialQqGateway(config.qq, config.owner, RecordingIngress(), FixedClock())
    running = asyncio.create_task(gateway.run_forever())
    try:
        await gateway.wait_ready(30)
        delivery_id = await gateway.send_active("QQ Time Agent 阶段 15 主动通知沙箱验证")
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


async def test_official_qq_owner_image_download_and_offline_ocr() -> None:
    config = load_runtime_config()
    ingress = RecordingImageIngress()
    gateway = OfficialQqGateway(config.qq, config.owner, ingress, FixedClock())
    running = asyncio.create_task(gateway.run_forever())
    media = OfficialQqMediaRoute(config.assets.max_bytes)
    try:
        await gateway.wait_ready(30)
        await gateway.send_active("请在90秒内发送一张清晰截图, 截图文字须包含: 阶段14OCR验证")
        await asyncio.wait_for(ingress.received.wait(), timeout=90)
        descriptor = ingress.assets[0]
        now = FixedClock().now()
        asset = SourceAsset.discover(
            uuid4(),
            descriptor.provider_asset_id,
            descriptor.provider_locator,
            AssetKind.IMAGE,
            descriptor.content_type,
            now,
            now + timedelta(hours=1),
            filename=descriptor.filename,
            declared_size=descriptor.declared_size,
        )
        content = await media.fetch(
            SourceAssetContext(asset, None, "sandbox-image", SourceType.QQ_DIRECT, None)
        )
        parser = DocumentAssetParser(
            IcalendarParser(),
            config.assets.max_pdf_pages,
            config.assets.max_image_pixels,
            config.assets.max_output_chars,
            config.assets.processing_timeout_seconds,
        )
        parsed = await parser.parse(
            content,
            NormalizableAssetKind.IMAGE,
            str(config.schedule.timezone),
        )
        assert "阶段14OCR验证" in parsed.text.replace(" ", "")
    finally:
        running.cancel()
        await media.close()
        with pytest.raises(asyncio.CancelledError):
            await running
