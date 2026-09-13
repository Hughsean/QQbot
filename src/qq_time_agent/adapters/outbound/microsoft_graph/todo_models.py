"""Microsoft Graph To Do DTO validation contained at the adapter boundary."""

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from qq_time_agent.modules.task_projection.contracts import (
    ExternalTaskChange,
    ExternalTaskDeltaPage,
    ExternalTaskList,
    ExternalTaskView,
    TaskProviderError,
)


class _GraphTaskList(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    list_id: str = Field(alias="id", min_length=1, max_length=1024)
    display_name: str = Field(alias="displayName", min_length=1, max_length=120)
    is_owner: bool = Field(alias="isOwner")
    is_shared: bool = Field(alias="isShared")
    well_known_name: str = Field(alias="wellknownListName", max_length=80)


class _GraphTaskBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    content: str = ""


class GraphTaskRecord(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    task_id: str = Field(alias="id", min_length=1, max_length=1024)
    status: str
    revision: str | None = Field(default=None, alias="@odata.etag", max_length=1024)
    body: _GraphTaskBody | None = None


class _GraphRemoved(BaseModel):
    model_config = ConfigDict(extra="ignore")

    reason: str = "changed"


class _GraphTaskChange(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    task_id: str = Field(alias="id", min_length=1, max_length=1024)
    status: str | None = None
    revision: str | None = Field(default=None, alias="@odata.etag", max_length=1024)
    removed: _GraphRemoved | None = Field(default=None, alias="@removed")


def map_list_page(
    response: httpx.Response,
) -> tuple[tuple[ExternalTaskList, ...], str | None]:
    try:
        raw_values, next_link = _page_values(response)
        values = tuple(_map_list(item) for item in raw_values)
        return values, next_link
    except (KeyError, TypeError, ValueError, ValidationError, AttributeError) as exc:
        raise TaskProviderError("PermanentProvider") from exc


def map_task_response(response: httpx.Response) -> ExternalTaskView:
    try:
        task = GraphTaskRecord.model_validate(response.json())
    except (ValueError, ValidationError, AttributeError) as exc:
        raise TaskProviderError("PermanentProvider") from exc
    return ExternalTaskView(task.task_id, task.revision, task.status == "completed")


def map_task_page(
    response: httpx.Response,
) -> tuple[tuple[GraphTaskRecord, ...], str | None]:
    try:
        raw_values, next_link = _page_values(response)
        return tuple(GraphTaskRecord.model_validate(item) for item in raw_values), next_link
    except (KeyError, TypeError, ValueError, ValidationError, AttributeError) as exc:
        raise TaskProviderError("PermanentProvider") from exc


def map_delta_page(response: httpx.Response) -> ExternalTaskDeltaPage:
    try:
        payload = response.json()
        raw_values = payload["value"]
        if not isinstance(raw_values, list):
            raise TypeError
        changes = tuple(_map_change(value) for value in raw_values)
        continuation = payload.get("@odata.nextLink") or payload.get("@odata.deltaLink")
        if not isinstance(continuation, str) or not continuation:
            raise TypeError
        return ExternalTaskDeltaPage(changes, continuation)
    except (KeyError, TypeError, ValueError, ValidationError, AttributeError) as exc:
        raise TaskProviderError("PermanentProvider") from exc


def _map_change(value: object) -> ExternalTaskChange:
    item = _GraphTaskChange.model_validate(value)
    return ExternalTaskChange(
        item.task_id,
        item.revision,
        item.status == "completed",
        item.removed is not None,
    )


def _map_list(value: object) -> ExternalTaskList:
    item = _GraphTaskList.model_validate(value)
    return ExternalTaskList(
        item.list_id,
        item.display_name,
        item.is_owner,
        item.is_shared,
        item.well_known_name,
    )


def _page_values(response: httpx.Response) -> tuple[list[object], str | None]:
    payload = response.json()
    raw_values = payload["value"]
    if not isinstance(raw_values, list):
        raise TypeError
    next_link = payload.get("@odata.nextLink")
    if next_link is not None and not isinstance(next_link, str):
        raise TypeError
    return raw_values, next_link
