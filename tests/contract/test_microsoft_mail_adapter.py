from datetime import UTC, datetime

import httpx
import pytest

from qq_time_agent.adapters.outbound.microsoft_graph.mail import MicrosoftGraphMailAdapter
from qq_time_agent.modules.credentials.contracts import CredentialHandle, CredentialKind
from qq_time_agent.modules.inbox.contracts import MailProviderError


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 8, 13, tzinfo=UTC)


def _handle() -> CredentialHandle:
    return CredentialHandle(
        "access-token",
        CredentialKind.ACCESS_TOKEN,
        datetime(2026, 8, 13, 1, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_graph_mail_maps_delta_page_without_provider_dto_leak() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "graph.microsoft.com"
        assert request.headers["Authorization"] == "Bearer access-token"
        assert "receivedDateTime" in str(request.url)
        return httpx.Response(
            200,
            json={
                "value": [
                    {
                        "id": "message-1",
                        "conversationId": "thread-1",
                        "internetMessageId": "<one@example.test>",
                        "sender": {
                            "emailAddress": {
                                "address": "sender@example.test",
                                "name": "Sender",
                            }
                        },
                        "toRecipients": [
                            {"emailAddress": {"address": "owner@example.test", "name": "Owner"}}
                        ],
                        "subject": "Meeting",
                        "receivedDateTime": "2026-08-12T08:00:00Z",
                        "changeKey": "change-1",
                        "hasAttachments": False,
                    },
                    {"id": "deleted-1", "@removed": {"reason": "deleted"}},
                ],
                "@odata.deltaLink": "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages/delta?$deltatoken=safe",
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = MicrosoftGraphMailAdapter(FixedClock(), client)
    page = await adapter.fetch_page(_handle(), None, datetime(2026, 8, 6, tzinfo=UTC))
    assert page.round_complete
    assert page.changes[0].sender.address == "sender@example.test"
    assert page.changes[1].removed

    async def content_handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/messages/message-1")
        return httpx.Response(
            200, json={"body": {"contentType": "text", "content": "Friday 17:00"}}
        )

    content_adapter = MicrosoftGraphMailAdapter(
        FixedClock(), httpx.AsyncClient(transport=httpx.MockTransport(content_handler))
    )
    complete = await content_adapter.fetch_content(_handle(), page.changes[0])
    assert complete.body == "Friday 17:00"


@pytest.mark.asyncio
async def test_graph_mail_rejects_untrusted_cursor_and_classifies_auth() -> None:
    adapter = MicrosoftGraphMailAdapter(FixedClock(), httpx.AsyncClient())
    with pytest.raises(ValueError, match="untrusted"):
        await adapter.fetch_page(
            _handle(), "https://evil.example/cursor", datetime(2026, 8, 6, tzinfo=UTC)
        )
    await adapter.close()

    async def unauthorized(_: httpx.Request) -> httpx.Response:
        return httpx.Response(401)

    adapter = MicrosoftGraphMailAdapter(
        FixedClock(), httpx.AsyncClient(transport=httpx.MockTransport(unauthorized))
    )
    with pytest.raises(MailProviderError, match="Authentication"):
        await adapter.fetch_page(_handle(), None, datetime(2026, 8, 6, tzinfo=UTC))


@pytest.mark.asyncio
async def test_graph_mail_honors_bounded_retry_after_with_jitter() -> None:
    attempts = 0
    delays: list[float] = []

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, headers={"Retry-After": "2"})
        return httpx.Response(
            200,
            json={
                "value": [],
                "@odata.deltaLink": "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages/delta?$deltatoken=done",
            },
        )

    async def sleep(delay: float) -> None:
        delays.append(delay)

    adapter = MicrosoftGraphMailAdapter(
        FixedClock(),
        httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        sleep=sleep,
        jitter=lambda: 0.25,
    )
    page = await adapter.fetch_page(_handle(), None, datetime(2026, 8, 6, tzinfo=UTC))
    assert page.round_complete
    assert attempts == 2
    assert delays == [2.25]


@pytest.mark.asyncio
async def test_graph_mail_accepts_documented_and_live_inbox_delta_paths_only() -> None:
    seen: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(
            200,
            json={
                "value": [],
                "@odata.deltaLink": (
                    "https://graph.microsoft.com/v1.0/"
                    "me/mailFolders('inbox')/messages/delta?$deltatoken=done"
                ),
            },
        )

    adapter = MicrosoftGraphMailAdapter(
        FixedClock(), httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    live_cursor = (
        "https://graph.microsoft.com/v1.0/me/mailFolders('inbox')/messages/delta?$deltatoken=live"
    )
    page = await adapter.fetch_page(_handle(), live_cursor, datetime(2026, 8, 6, tzinfo=UTC))
    assert page.round_complete
    assert seen == ["/v1.0/me/mailFolders('inbox')/messages/delta"]

    with pytest.raises(ValueError, match="unexpected"):
        await adapter.fetch_page(
            _handle(),
            "https://graph.microsoft.com/v1.0/me/mailFolders/archive/messages/delta?token=x",
            datetime(2026, 8, 6, tzinfo=UTC),
        )


def test_access_handle_expires_and_cannot_be_serialized() -> None:
    handle = _handle()
    with pytest.raises(ValueError, match="expired"):
        handle.reveal(datetime(2026, 8, 13, 2, tzinfo=UTC))
