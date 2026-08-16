"""Bounded downloader for attachment URLs emitted by official QQ events."""

from urllib.parse import urlsplit

import httpx

from qq_time_agent.modules.inbox.application.asset_ports import SourceAssetContext
from qq_time_agent.modules.inbox.contracts import MailProviderError

_ALLOWED_SUFFIXES = (".qq.com", ".qq.com.cn", ".qpic.cn", ".gtimg.cn")


class OfficialQqMediaRoute:
    def __init__(
        self,
        max_bytes: int,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if max_bytes < 1:
            raise ValueError("QQ media maximum bytes must be positive")
        self._max_bytes = max_bytes
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(10.0),
            follow_redirects=False,
        )
        self._owns_client = client is None

    async def fetch(self, context: SourceAssetContext) -> bytes:
        locator = context.asset.provider_locator
        _validate_locator(locator)
        try:
            response = await self._client.get(locator, headers={"Accept": "image/*"})
        except httpx.TimeoutException as exc:
            raise MailProviderError("TransientProvider") from exc
        except httpx.HTTPError as exc:
            raise MailProviderError("ProviderProtocol") from exc
        if response.is_redirect:
            raise MailProviderError("ProviderProtocol")
        if response.status_code in {408, 429} or response.status_code >= 500:
            raise MailProviderError("TransientProvider")
        if response.status_code != 200:
            raise MailProviderError("ProviderProtocol")
        declared = response.headers.get("content-length")
        if declared is not None and (not declared.isdigit() or int(declared) > self._max_bytes):
            raise MailProviderError("AssetTooLarge")
        content = response.content
        if len(content) > self._max_bytes:
            raise MailProviderError("AssetTooLarge")
        return content

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()


def _validate_locator(locator: str) -> None:
    parsed = urlsplit(locator)
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in {None, 443}
        or not any(host.endswith(suffix) for suffix in _ALLOWED_SUFFIXES)
        or parsed.fragment
    ):
        raise MailProviderError("ProviderProtocol")
