import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest

from qq_time_agent.adapters.outbound.microsoft_graph.todo import MicrosoftGraphTodoAdapter
from qq_time_agent.modules.connections.contracts import TaskAccessGrant
from qq_time_agent.modules.credentials.contracts import CredentialHandle, CredentialKind
from qq_time_agent.modules.task_projection.contracts import ExternalTaskDraft, TaskProviderError


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
    assert "$select" not in calls[0].url.params
    assert calls[0].url.params["$top"] == "100"
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


def _draft() -> ExternalTaskDraft:
    start = datetime(2026, 9, 13, 7, tzinfo=UTC)
    return ExternalTaskDraft(
        "qq-time-agent:stable",
        "南瑞继保测评",
        start,
        start + timedelta(hours=1),
        "Asia/Shanghai",
    )


@pytest.mark.asyncio
async def test_upsert_creates_task_with_reminder_disabled() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"value": []})
        assert request.method == "POST"
        return httpx.Response(
            201,
            json={"id": "task-one", "status": "notStarted", "@odata.etag": "rev-one"},
        )

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://graph.microsoft.com"
    )
    result = await MicrosoftGraphTodoAdapter(FixedClock(), client=client).upsert_task(
        _grant(), "managed", _draft(), None
    )
    await client.aclose()

    assert result.task_ref == "task-one" and result.revision == "rev-one"
    payload = json.loads(calls[-1].content)
    assert payload["isReminderOn"] is False
    assert "qq-time-agent:stable" in payload["body"]["content"]
    assert payload["startDateTime"]["timeZone"] == "UTC"


@pytest.mark.asyncio
async def test_upsert_recovers_existing_marker_instead_of_creating_duplicate() -> None:
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "id": "recovered",
                            "status": "notStarted",
                            "body": {"content": "同步标记: qq-time-agent:stable"},
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={"id": "recovered", "status": "notStarted", "@odata.etag": "rev-two"},
        )

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://graph.microsoft.com"
    )
    result = await MicrosoftGraphTodoAdapter(FixedClock(), client=client).upsert_task(
        _grant(), "managed", _draft(), None
    )
    await client.aclose()

    assert result.task_ref == "recovered"
    assert methods == ["GET", "PATCH"]


@pytest.mark.asyncio
async def test_ambiguous_create_recovers_by_marker_without_second_post() -> None:
    methods: list[str] = []
    task_visible = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal task_visible
        methods.append(request.method)
        if request.method == "POST":
            task_visible = True
            raise httpx.ReadTimeout("ambiguous", request=request)
        if request.method == "GET":
            values = (
                [
                    {
                        "id": "committed-before-timeout",
                        "status": "notStarted",
                        "body": {"content": "qq-time-agent:stable"},
                    }
                ]
                if task_visible
                else []
            )
            return httpx.Response(200, json={"value": values})
        return httpx.Response(
            200,
            json={"id": "committed-before-timeout", "status": "notStarted"},
        )

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://graph.microsoft.com"
    )
    result = await MicrosoftGraphTodoAdapter(FixedClock(), client=client).upsert_task(
        _grant(), "managed", _draft(), None
    )
    await client.aclose()

    assert result.task_ref == "committed-before-timeout"
    assert methods == ["GET", "POST", "GET", "PATCH"]


@pytest.mark.asyncio
async def test_close_completes_or_deletes_and_missing_task_is_idempotent() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(404 if len(calls) == 2 else 200)

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://graph.microsoft.com"
    )
    adapter = MicrosoftGraphTodoAdapter(FixedClock(), client=client)
    await adapter.close_task(_grant(), "managed", "complete-me", completed=True)
    await adapter.close_task(_grant(), "managed", "cancel-me", completed=False)
    await client.aclose()

    assert [call.method for call in calls] == ["PATCH", "DELETE"]
    assert json.loads(calls[0].content) == {"status": "completed"}


@pytest.mark.asyncio
async def test_strong_get_and_delta_are_provider_neutral() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path.endswith("/tasks/task-one"):
            return httpx.Response(
                200,
                json={"id": "task-one", "status": "completed", "@odata.etag": "rev-two"},
            )
        return httpx.Response(
            200,
            json={
                "value": [
                    {"id": "task-one", "status": "completed", "@odata.etag": "rev-two"},
                    {"id": "task-gone", "@removed": {"reason": "deleted"}},
                ],
                "@odata.deltaLink": (
                    "https://graph.microsoft.com/v1.0/me/todo/lists/managed/tasks/delta"
                    "?$deltatoken=opaque"
                ),
            },
        )

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://graph.microsoft.com"
    )
    adapter = MicrosoftGraphTodoAdapter(FixedClock(), client=client, max_attempts=1)
    task = await adapter.get_task(_grant(), "managed", "task-one")
    page = await adapter.fetch_delta(_grant(), "managed", None)
    await client.aclose()

    assert task is not None and task.completed and task.revision == "rev-two"
    assert [(item.task_ref, item.completed, item.removed) for item in page.changes] == [
        ("task-one", True, False),
        ("task-gone", False, True),
    ]
    assert "$deltatoken=opaque" in page.continuation
    assert calls[1].url.path.endswith("/tasks/delta")


@pytest.mark.asyncio
async def test_missing_task_and_untrusted_delta_cursor_are_safe() -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(404)),
        base_url="https://graph.microsoft.com",
    )
    adapter = MicrosoftGraphTodoAdapter(FixedClock(), client=client, max_attempts=1)
    assert await adapter.get_task(_grant(), "managed", "missing") is None
    with pytest.raises(TaskProviderError, match="SecurityPolicy"):
        await adapter.fetch_delta(
            _grant(), "managed", "https://attacker.example/tasks/delta?token=secret"
        )
    await client.aclose()


@pytest.mark.asyncio
async def test_delta_accepts_graph_normalized_provider_id_path() -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={
                    "value": [],
                    "@odata.deltaLink": (
                        "https://graph.microsoft.com/v1.0/me/todo/lists/opaque=id/tasks/delta"
                        "?$deltatoken=opaque"
                    ),
                },
            )
        ),
        base_url="https://graph.microsoft.com",
    )
    adapter = MicrosoftGraphTodoAdapter(FixedClock(), client=client, max_attempts=1)
    page = await adapter.fetch_delta(_grant(), "opaque=id", None)
    await client.aclose()

    assert page.changes == ()
    assert page.continuation.endswith("$deltatoken=opaque")
