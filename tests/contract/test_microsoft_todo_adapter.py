from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest

from qq_time_agent.adapters.outbound.microsoft_graph.todo import MicrosoftGraphTodoAdapter
from qq_time_agent.modules.connections.contracts import TaskAccessGrant
from qq_time_agent.modules.credentials.contracts import CredentialHandle, CredentialKind
from qq_time_agent.modules.task_projection.contracts import TaskProviderError


@dataclass
class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 9, 13, tzinfo=UTC)


def _grant() -> TaskAccessGrant:
    return TaskAccessGrant(
        uuid4(),
        "owner",
        "account",
        CredentialHandle("synthetic-task-access", CredentialKind.ACCESS_TOKEN, None),
    )


@pytest.mark.asyncio
async def test_lists_are_paginated_and_mapped_without_provider_dto_leak() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.headers["Authorization"] == "Bearer synthetic-task-access"
        if len(calls) == 1:
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "id": "first",
                            "displayName": "Tasks",
                            "isOwner": True,
                            "isShared": False,
                            "wellknownListName": "defaultList",
                            "providerOnly": "discarded",
                        }
                    ],
                    "@odata.nextLink": (
                        "https://graph.microsoft.com/v1.0/me/todo/lists?$skiptoken=next"
                    ),
                },
            )
        return httpx.Response(
            200,
            json={
                "value": [
                    {
                        "id": "managed",
                        "displayName": "小智建议",
                        "isOwner": True,
                        "isShared": False,
                        "wellknownListName": "none",
                    }
                ]
            },
        )

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://graph.microsoft.com"
    )
    adapter = MicrosoftGraphTodoAdapter(FixedClock(), client=client)
    values = await adapter.list_task_lists(_grant())
    await client.aclose()

    assert [(item.list_ref, item.display_name) for item in values] == [
        ("first", "Tasks"),
        ("managed", "小智建议"),
    ]
    assert "$select" in calls[0].url.params
    assert "$skiptoken" in calls[1].url.params


@pytest.mark.asyncio
async def test_untrusted_pagination_link_and_provider_errors_are_classified() -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={
                    "value": [],
                    "@odata.nextLink": "https://attacker.example/todo/lists?token=secret",
                },
            )
        ),
        base_url="https://graph.microsoft.com",
    )
    adapter = MicrosoftGraphTodoAdapter(FixedClock(), client=client, max_attempts=1)
    with pytest.raises(TaskProviderError, match="SecurityPolicy"):
        await adapter.list_task_lists(_grant())
    await client.aclose()

    forbidden = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(403)),
        base_url="https://graph.microsoft.com",
    )
    adapter = MicrosoftGraphTodoAdapter(FixedClock(), client=forbidden, max_attempts=1)
    with pytest.raises(TaskProviderError, match="Authorization"):
        await adapter.list_task_lists(_grant())
    await forbidden.aclose()
