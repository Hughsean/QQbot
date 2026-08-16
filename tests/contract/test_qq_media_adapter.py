from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest

from qq_time_agent.adapters.outbound.qq.media import OfficialQqMediaRoute
from qq_time_agent.contracts.source import SourceType
from qq_time_agent.modules.inbox.application.asset_ports import SourceAssetContext
from qq_time_agent.modules.inbox.contracts import MailProviderError
from qq_time_agent.modules.inbox.domain.assets import AssetKind, SourceAsset

NOW = datetime(2026, 8, 14, tzinfo=UTC)
PNG = b"\x89PNG\r\n\x1a\nsynthetic"


def _context(locator: str) -> SourceAssetContext:
    asset = SourceAsset.discover(
        uuid4(),
        "media-1",
        locator,
        AssetKind.IMAGE,
        "image/png",
        NOW,
        NOW + timedelta(hours=24),
        filename="screenshot.png",
        declared_size=len(PNG),
    )
    return SourceAssetContext(asset, None, "message-1", SourceType.QQ_DIRECT, "qq:message-1")


@pytest.mark.asyncio
async def test_qq_media_download_is_https_allowlisted_and_bounded() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, content=PNG, headers={"content-length": str(len(PNG))})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)
    route = OfficialQqMediaRoute(1024, client)
    content = await route.fetch(_context("https://gchat.qpic.cn/image/opaque"))
    assert content == PNG
    assert requests[0].headers["accept"] == "image/*"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "locator",
    (
        "http://gchat.qpic.cn/image/opaque",
        "https://127.0.0.1/image/opaque",
        "https://gchat.qpic.cn@127.0.0.1/image/opaque",
        "https://gchat.qpic.cn:8443/image/opaque",
    ),
)
async def test_qq_media_download_rejects_ssrf_locators(locator: str) -> None:
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200)))
    route = OfficialQqMediaRoute(1024, client)
    with pytest.raises(MailProviderError, match="ProviderProtocol"):
        await route.fetch(_context(locator))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    (
        httpx.Response(302, headers={"location": "https://gchat.qpic.cn/other"}),
        httpx.Response(200, content=PNG, headers={"content-length": "2048"}),
    ),
)
async def test_qq_media_download_rejects_redirect_and_declared_oversize(
    response: httpx.Response,
) -> None:
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: response))
    route = OfficialQqMediaRoute(1024, client)
    with pytest.raises(MailProviderError):
        await route.fetch(_context("https://gchat.qpic.cn/image/opaque"))
