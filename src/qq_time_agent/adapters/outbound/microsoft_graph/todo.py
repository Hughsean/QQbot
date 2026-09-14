"""Microsoft Graph To Do adapter with strict DTO containment."""

import asyncio
import random
from collections.abc import Awaitable, Callable
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from qq_time_agent.adapters.outbound.microsoft_graph.todo_models import (
    GraphTaskRecord,
    map_delta_page,
    map_list_page,
    map_task_page,
    map_task_response,
)
from qq_time_agent.adapters.outbound.microsoft_graph.todo_values import (
    task_delta_path,
    task_path,
    task_payload,
    tasks_path,
)
from qq_time_agent.contracts.clock import Clock
from qq_time_agent.modules.connections.contracts import TaskAccessGrant
from qq_time_agent.modules.task_projection.contracts import (
    ExternalTaskDeltaPage,
    ExternalTaskDraft,
    ExternalTaskList,
    ExternalTaskView,
    TaskProviderError,
)

GRAPH_ORIGIN = "https://graph.microsoft.com"
LISTS_PATH = "/v1.0/me/todo/lists"


class MicrosoftGraphTodoAdapter:
    def __init__(
        self,
        clock: Clock,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 15.0,
        max_attempts: int = 2,
        max_pages: int = 10,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        jitter: Callable[[], float] = random.random,
    ) -> None:
        if max_attempts < 1 or max_pages < 1:
            raise ValueError("Graph To Do limits must be positive")
        self._clock = clock
        self._client = client or httpx.AsyncClient(base_url=GRAPH_ORIGIN, timeout=timeout_seconds)
        self._owns_client = client is None
        self._max_attempts = max_attempts
        self._max_pages = max_pages
        self._sleep = sleep
        self._jitter = jitter

    async def list_task_lists(self, access_grant: TaskAccessGrant) -> tuple[ExternalTaskList, ...]:
        token = access_grant.task_credential.reveal(self._clock.now())
        url = LISTS_PATH
        params: dict[str, str] | None = {"$top": "100"}
        values: list[ExternalTaskList] = []
        for _ in range(self._max_pages):
            response = await self._request("GET", url, token, params=params)
            page, next_link = map_list_page(response)
            values.extend(page)
            if next_link is None:
                return tuple(values)
            _validate_next_link(next_link)
            url, params = next_link, None
        raise TaskProviderError("PermanentProvider")

    async def upsert_task(
        self,
        access_grant: TaskAccessGrant,
        list_ref: str,
        draft: ExternalTaskDraft,
        task_ref: str | None,
    ) -> ExternalTaskView:
        token = access_grant.task_credential.reveal(self._clock.now())
        found = (
            None
            if task_ref is not None
            else await self._find_task(token, list_ref, draft.stable_marker)
        )
        current_ref = task_ref or (None if found is None else found.task_id)
        payload = task_payload(draft)
        if current_ref is not None:
            response = await self._request(
                "PATCH",
                task_path(list_ref, current_ref),
                token,
                json=payload,
                allow_not_found=True,
            )
            if response.status_code != 404:
                return map_task_response(response)
            recovered = await self._find_task(token, list_ref, draft.stable_marker)
            if recovered is not None:
                response = await self._request(
                    "PATCH", task_path(list_ref, recovered.task_id), token, json=payload
                )
                return map_task_response(response)
        try:
            response = await self._request(
                "POST",
                tasks_path(list_ref),
                token,
                json=payload,
                retry_transient=False,
            )
        except TaskProviderError as exc:
            if exc.failure_class not in {"RateLimit", "TransientProvider"}:
                raise
            recovered = await self._find_task(token, list_ref, draft.stable_marker)
            if recovered is None:
                raise
            response = await self._request(
                "PATCH", task_path(list_ref, recovered.task_id), token, json=payload
            )
        return map_task_response(response)

    async def find_task(
        self,
        access_grant: TaskAccessGrant,
        list_ref: str,
        stable_marker: str,
    ) -> ExternalTaskView | None:
        token = access_grant.task_credential.reveal(self._clock.now())
        task = await self._find_task(token, list_ref, stable_marker)
        if task is None:
            return None
        return ExternalTaskView(task.task_id, task.revision, task.status == "completed")

    async def get_task(
        self,
        access_grant: TaskAccessGrant,
        list_ref: str,
        task_ref: str,
    ) -> ExternalTaskView | None:
        token = access_grant.task_credential.reveal(self._clock.now())
        response = await self._request(
            "GET",
            task_path(list_ref, task_ref),
            token,
            params={"$select": "id,status"},
            allow_not_found=True,
        )
        if response.status_code == 404:
            return None
        return map_task_response(response)

    async def fetch_delta(
        self,
        access_grant: TaskAccessGrant,
        list_ref: str,
        continuation: str | None,
    ) -> ExternalTaskDeltaPage:
        token = access_grant.task_credential.reveal(self._clock.now())
        url = continuation or task_delta_path(list_ref)
        if continuation is not None:
            _validate_delta_link(continuation, list_ref)
        response = await self._request(
            "GET",
            url,
            token,
            params=None if continuation else {"$select": "id,status"},
        )
        page = map_delta_page(response)
        _validate_delta_link(page.continuation, list_ref)
        return page

    async def close_task(
        self,
        access_grant: TaskAccessGrant,
        list_ref: str,
        task_ref: str,
        completed: bool,
    ) -> None:
        token = access_grant.task_credential.reveal(self._clock.now())
        method = "PATCH" if completed else "DELETE"
        payload: dict[str, object] | None = {"status": "completed"} if completed else None
        await self._request(
            method,
            task_path(list_ref, task_ref),
            token,
            json=payload,
            allow_not_found=True,
        )

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _find_task(self, token: str, list_ref: str, marker: str) -> GraphTaskRecord | None:
        url = tasks_path(list_ref)
        params: dict[str, str] | None = {"$select": "id,status,body", "$top": "100"}
        for _ in range(self._max_pages):
            response = await self._request("GET", url, token, params=params)
            tasks, next_link = map_task_page(response)
            matches = tuple(
                task for task in tasks if task.body is not None and marker in task.body.content
            )
            if len(matches) > 1:
                raise TaskProviderError("ProviderConflict")
            if matches:
                return matches[0]
            if next_link is None:
                return None
            _validate_task_next_link(next_link, list_ref)
            url, params = next_link, None
        raise TaskProviderError("PermanentProvider")

    async def _request(
        self,
        method: str,
        url: str,
        token: str,
        *,
        params: dict[str, str] | None = None,
        json: dict[str, object] | None = None,
        allow_not_found: bool = False,
        retry_transient: bool = True,
    ) -> httpx.Response:
        for attempt in range(self._max_attempts):
            try:
                response = await self._client.request(
                    method,
                    url,
                    params=params,
                    json=json,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/json",
                    },
                )
            except (httpx.NetworkError, httpx.TimeoutException) as exc:
                if attempt + 1 == self._max_attempts or not retry_transient:
                    raise TaskProviderError("TransientProvider") from exc
                await self._sleep(_retry_delay(attempt, None, self._jitter()))
                continue
            if allow_not_found and response.status_code == 404:
                return response
            failure = _status_failure(response.status_code)
            if failure is None:
                return response
            if (
                retry_transient
                and failure in {"RateLimit", "TransientProvider"}
                and attempt + 1 < self._max_attempts
            ):
                await self._sleep(_retry_delay(attempt, response, self._jitter()))
                continue
            raise TaskProviderError(failure)
        raise AssertionError("unreachable")


def _validate_next_link(value: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.hostname != "graph.microsoft.com":
        raise TaskProviderError("SecurityPolicy")
    if parsed.path != LISTS_PATH:
        raise TaskProviderError("SecurityPolicy")


def _validate_task_next_link(value: str, list_ref: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.hostname != "graph.microsoft.com":
        raise TaskProviderError("SecurityPolicy")
    if parsed.path != tasks_path(list_ref):
        raise TaskProviderError("SecurityPolicy")


def _validate_delta_link(value: str, list_ref: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.netloc != "graph.microsoft.com":
        raise TaskProviderError("SecurityPolicy")
    prefix, suffix = f"{LISTS_PATH}/", "/tasks/delta"
    if not parsed.path.startswith(prefix) or not parsed.path.endswith(suffix):
        raise TaskProviderError("SecurityPolicy")
    encoded_ref = parsed.path[len(prefix) : -len(suffix)]
    if not encoded_ref or "/" in encoded_ref or unquote(encoded_ref) != list_ref:
        raise TaskProviderError("SecurityPolicy")
    query = parse_qs(parsed.query, keep_blank_values=True)
    if not ({"$deltatoken", "$skiptoken"} & query.keys()) or parsed.fragment:
        raise TaskProviderError("SecurityPolicy")


def _status_failure(status: int) -> str | None:
    if 200 <= status < 300:
        return None
    if status == 401:
        return "Authentication"
    if status == 403:
        return "Authorization"
    if status == 429:
        return "RateLimit"
    if status == 410:
        return "CursorInvalid"
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
