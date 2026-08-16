"""Microsoft Graph mail delta adapter with strict provider-neutral mapping."""

import asyncio
import random
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import datetime
from urllib.parse import quote, urlparse

import httpx

from qq_time_agent.adapters.outbound.microsoft_graph.mail_mapping import (
    map_attachment,
    map_change,
    optional_string,
)
from qq_time_agent.contracts.clock import Clock
from qq_time_agent.modules.credentials.contracts import CredentialHandle
from qq_time_agent.modules.inbox.contracts import (
    MailAttachmentMetadata,
    MailChange,
    MailDeltaPage,
    MailProviderError,
)

GRAPH_ORIGIN = "https://graph.microsoft.com"
DELTA_URL = f"{GRAPH_ORIGIN}/v1.0/me/mailFolders/inbox/messages/delta"
ALLOWED_DELTA_PATHS = {
    "/v1.0/me/mailFolders/inbox/messages/delta",
    "/v1.0/me/mailFolders('inbox')/messages/delta",
}
SELECT_FIELDS = ",".join(
    (
        "id",
        "conversationId",
        "internetMessageId",
        "sender",
        "toRecipients",
        "subject",
        "receivedDateTime",
        "changeKey",
        "hasAttachments",
    )
)


class MicrosoftGraphMailAdapter:
    def __init__(
        self,
        clock: Clock,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 20.0,
        max_attempts: int = 3,
        max_attachment_bytes: int = 20 * 1024 * 1024,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        jitter: Callable[[], float] = random.random,
    ) -> None:
        self._clock = clock
        self._client = client or httpx.AsyncClient(base_url=GRAPH_ORIGIN, timeout=timeout_seconds)
        self._owns_client = client is None
        if max_attachment_bytes < 1:
            raise ValueError("attachment maximum bytes must be positive")
        self._max_attempts = max_attempts
        self._max_attachment_bytes = max_attachment_bytes
        self._sleep = sleep
        self._jitter = jitter

    async def fetch_page(
        self,
        mail_credential: CredentialHandle,
        account_id: str,
        cursor_url: str | None,
        since: datetime,
    ) -> MailDeltaPage:
        del account_id
        _require_aware(since)
        url, params = _request(cursor_url, since)
        token = mail_credential.reveal(self._clock.now())
        response = await self._get(url, token, params)
        try:
            payload = response.json()
            raw_changes = payload["value"]
            if not isinstance(raw_changes, list):
                raise TypeError
            changes = tuple(map_change(item) for item in raw_changes)
            continuation, complete = _continuation(payload)
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise MailProviderError("PermanentProvider") from exc
        return MailDeltaPage(changes, continuation, complete)

    async def fetch_content(
        self, mail_credential: CredentialHandle, account_id: str, change: MailChange
    ) -> MailChange:
        del account_id
        if change.removed:
            raise ValueError("removed mail has no content")
        token = mail_credential.reveal(self._clock.now())
        message_id = quote(change.external_id, safe="")
        response = await self._get(
            f"{GRAPH_ORIGIN}/v1.0/me/messages/{message_id}",
            token,
            {"$select": "body"},
        )
        try:
            payload = response.json()
            body = payload["body"]
            if not isinstance(body, dict):
                raise TypeError
            content = optional_string(body, "content") or ""
            content_type = (optional_string(body, "contentType") or "text").lower()
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise MailProviderError("PermanentProvider") from exc
        attachments = (
            await self._attachment_metadata(token, message_id) if change.has_attachments else ()
        )
        return replace(
            change,
            body=content,
            body_content_type=content_type,
            attachments=attachments,
        )

    async def fetch_attachment(
        self,
        mail_credential: CredentialHandle,
        account_id: str,
        message_external_id: str,
        attachment: MailAttachmentMetadata,
    ) -> bytes:
        del account_id
        if not attachment.provider_locator:
            raise MailProviderError("PermanentProvider")
        token = mail_credential.reveal(self._clock.now())
        message_id = quote(message_external_id, safe="")
        attachment_id = quote(attachment.provider_locator, safe="")
        response = await self._get(
            f"{GRAPH_ORIGIN}/v1.0/me/messages/{message_id}/attachments/{attachment_id}/$value",
            token,
            None,
        )
        declared = response.headers.get("Content-Length")
        try:
            declared_size = None if declared is None else int(declared)
        except ValueError as exc:
            raise MailProviderError("PermanentProvider") from exc
        if declared_size is not None and declared_size > self._max_attachment_bytes:
            raise MailProviderError("AssetTooLarge")
        if not response.content or len(response.content) > self._max_attachment_bytes:
            raise MailProviderError("AssetTooLarge")
        return response.content

    async def _attachment_metadata(
        self, token: str, message_id: str
    ) -> tuple[MailAttachmentMetadata, ...]:
        response = await self._get(
            f"{GRAPH_ORIGIN}/v1.0/me/messages/{message_id}/attachments",
            token,
            {"$select": "id,name,contentType,size,isInline", "$top": "100"},
        )
        try:
            payload = response.json()
            raw = payload["value"]
            if not isinstance(raw, list) or "@odata.nextLink" in payload:
                raise TypeError
            return tuple(map_attachment(value) for value in raw)
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise MailProviderError("PermanentProvider") from exc

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _get(self, url: str, token: str, params: dict[str, str] | None) -> httpx.Response:
        for attempt in range(self._max_attempts):
            try:
                response = await self._client.get(
                    url,
                    params=params,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Prefer": 'outlook.body-content-type="text", odata.maxpagesize=50',
                    },
                )
            except (httpx.NetworkError, httpx.TimeoutException) as exc:
                if attempt + 1 == self._max_attempts:
                    raise MailProviderError("TransientProvider") from exc
                await self._sleep(_retry_delay(attempt, None, self._jitter()))
                continue
            failure = _status_failure(response.status_code)
            if failure is None:
                return response
            if failure in {"RateLimit", "TransientProvider"} and attempt + 1 < self._max_attempts:
                await self._sleep(_retry_delay(attempt, response, self._jitter()))
                continue
            raise MailProviderError(failure)
        raise AssertionError("unreachable")


def _request(cursor_url: str | None, since: datetime) -> tuple[str, dict[str, str] | None]:
    if cursor_url is not None:
        _validate_cursor(cursor_url)
        return cursor_url, None
    return DELTA_URL, {
        "$select": SELECT_FIELDS,
        "$filter": f"receivedDateTime ge {since.isoformat().replace('+00:00', 'Z')}",
        "$orderby": "receivedDateTime desc",
    }


def _continuation(payload: dict[str, object]) -> tuple[str, bool]:
    next_link = payload.get("@odata.nextLink")
    delta_link = payload.get("@odata.deltaLink")
    if isinstance(next_link, str):
        _validate_cursor(next_link)
        return next_link, False
    if isinstance(delta_link, str):
        _validate_cursor(delta_link)
        return delta_link, True
    raise ValueError("Graph delta page has no continuation")


def _validate_cursor(value: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.hostname != "graph.microsoft.com":
        raise ValueError("untrusted Graph cursor URL")
    if parsed.path not in ALLOWED_DELTA_PATHS:
        raise ValueError("unexpected Graph cursor path")


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timezone-aware datetime required")


def _status_failure(status: int) -> str | None:
    if 200 <= status < 300:
        return None
    if status == 401:
        return "Authentication"
    if status == 403:
        return "Authorization"
    if status == 429:
        return "RateLimit"
    if status >= 500:
        return "TransientProvider"
    return "PermanentProvider"


def _retry_delay(attempt: int, response: httpx.Response | None, jitter: float) -> float:
    retry_after = 0.0
    if response is not None:
        try:
            retry_after = float(response.headers.get("Retry-After", "0"))
        except ValueError:
            retry_after = 0.0
    backoff = max(retry_after, min(30.0, 2.0**attempt))
    return min(30.0, backoff + max(0.0, min(jitter, 1.0)))
