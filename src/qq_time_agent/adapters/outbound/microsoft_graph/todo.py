"""Microsoft Graph To Do adapter with strict DTO containment."""

import asyncio
import random
from collections.abc import Awaitable, Callable
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from qq_time_agent.contracts.clock import Clock
from qq_time_agent.modules.connections.contracts import TaskAccessGrant
from qq_time_agent.modules.task_projection.contracts import ExternalTaskList, TaskProviderError

GRAPH_ORIGIN = "https://graph.microsoft.com"
LISTS_PATH = "/v1.0/me/todo/lists"
LIST_SELECT = "id,displayName,isOwner,isShared,wellknownListName"


class _GraphTaskList(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    list_id: str = Field(alias="id", min_length=1, max_length=1024)
    display_name: str = Field(alias="displayName", min_length=1, max_length=120)
    is_owner: bool = Field(alias="isOwner")
    is_shared: bool = Field(alias="isShared")
    well_known_name: str = Field(alias="wellknownListName", max_length=80)


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
        params: dict[str, str] | None = {"$select": LIST_SELECT, "$top": "100"}
        values: list[ExternalTaskList] = []
        for _ in range(self._max_pages):
            response = await self._get(url, token, params)
            page, next_link = _map_page(response)
            values.extend(page)
            if next_link is None:
                return tuple(values)
            _validate_next_link(next_link)
            url, params = next_link, None
        raise TaskProviderError("PermanentProvider")

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
                        "Accept": "application/json",
                    },
                )
            except (httpx.NetworkError, httpx.TimeoutException) as exc:
                if attempt + 1 == self._max_attempts:
                    raise TaskProviderError("TransientProvider") from exc
                await self._sleep(_retry_delay(attempt, None, self._jitter()))
                continue
            failure = _status_failure(response.status_code)
            if failure is None:
                return response
            if failure in {"RateLimit", "TransientProvider"} and attempt + 1 < self._max_attempts:
                await self._sleep(_retry_delay(attempt, response, self._jitter()))
                continue
            raise TaskProviderError(failure)
        raise AssertionError("unreachable")


def _map_page(response: httpx.Response) -> tuple[tuple[ExternalTaskList, ...], str | None]:
    try:
        payload = response.json()
        raw_values = payload["value"]
        if not isinstance(raw_values, list):
            raise TypeError
        values = tuple(_map_list(item) for item in raw_values)
        next_link = payload.get("@odata.nextLink")
        if next_link is not None and not isinstance(next_link, str):
            raise TypeError
        return values, next_link
    except (KeyError, TypeError, ValueError, ValidationError, AttributeError) as exc:
        raise TaskProviderError("PermanentProvider") from exc


def _map_list(value: object) -> ExternalTaskList:
    item = _GraphTaskList.model_validate(value)
    return ExternalTaskList(
        item.list_id,
        item.display_name,
        item.is_owner,
        item.is_shared,
        item.well_known_name,
    )


def _validate_next_link(value: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.hostname != "graph.microsoft.com":
        raise TaskProviderError("SecurityPolicy")
    if parsed.path != LISTS_PATH:
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
