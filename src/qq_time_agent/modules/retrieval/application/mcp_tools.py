"""Small local MCP-compatible, read-only RAG tool registry."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime

from qq_time_agent.modules.retrieval.contracts import (
    RetrievalFilters,
    RetrievalPort,
    RetrievedChunk,
)

ToolHandler = Callable[[str, dict[str, object]], Awaitable[object]]


@dataclass(frozen=True, slots=True)
class RagToolDefinition:
    name: str
    description: str
    input_schema: dict[str, object]
    handler: ToolHandler


class RagToolRegistry:
    """Owner-scoped tool surface suitable for injection into an MCP client."""

    def __init__(self, retrieval: RetrievalPort) -> None:
        self._retrieval = retrieval
        self._tools = {
            "search_knowledge": RagToolDefinition(
                "search_knowledge",
                "Search owner-scoped knowledge with hybrid retrieval.",
                _schema(),
                self._search,
            ),
            "get_source": RagToolDefinition(
                "get_source",
                "Retrieve chunks belonging to one source reference.",
                _schema(required=("source_ref",)),
                self._source,
            ),
            "list_related_events": RagToolDefinition(
                "list_related_events",
                "Find related mail and QQ event records without mutating Agenda.",
                _schema(),
                self._related,
            ),
        }

    def definitions(self) -> tuple[RagToolDefinition, ...]:
        return tuple(self._tools.values())

    async def call(self, name: str, owner_id: str, arguments: dict[str, object]) -> object:
        if owner_id != "owner":
            raise PermissionError("RAG tools are owner-scoped")
        tool = self._tools.get(name)
        if tool is None:
            raise ValueError("unknown RAG tool")
        return await tool.handler(owner_id, arguments)

    async def _search(self, owner_id: str, arguments: dict[str, object]) -> object:
        del owner_id
        query = _string(arguments, "query")
        return _render(await self._retrieve(query, _filters(arguments), _limit(arguments)))

    async def _source(self, owner_id: str, arguments: dict[str, object]) -> object:
        del owner_id
        source_ref = _string(arguments, "source_ref")
        values = await self._retrieve(source_ref, RetrievalFilters(), 30)
        return _render(tuple(value for value in values if value.source_ref == source_ref))

    async def _related(self, owner_id: str, arguments: dict[str, object]) -> object:
        del owner_id
        filters = _filters(arguments)
        filters = RetrievalFilters(
            ("MICROSOFT_MAIL", "QQ_MAIL", "QQ_DIRECT", "QQ_FORWARD"),
            filters.occurred_after,
            filters.occurred_before,
        )
        query = _string(arguments, "query")
        return _render(await self._retrieve(query, filters, _limit(arguments)))

    async def _retrieve(
        self, query: str, filters: RetrievalFilters, limit: int
    ) -> tuple[RetrievedChunk, ...]:
        return await self._retrieval.retrieve(query, filters, limit)


def _schema(required: tuple[str, ...] = ()) -> dict[str, object]:
    properties: dict[str, object] = {
        "query": {"type": "string", "maxLength": 6000},
        "source_ref": {"type": "string", "maxLength": 512},
        "source_types": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
        "limit": {"type": "integer", "minimum": 1, "maximum": 30},
        "occurred_after": {"type": "string", "format": "date-time"},
        "occurred_before": {"type": "string", "format": "date-time"},
    }
    return {"type": "object", "properties": properties, "required": list(required)}


def _string(arguments: dict[str, object], name: str) -> str:
    value = arguments.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")
    return value.strip()


def _limit(arguments: dict[str, object]) -> int:
    value = arguments.get("limit", 10)
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 30:
        raise ValueError("limit must be between 1 and 30")
    return value


def _filters(arguments: dict[str, object]) -> RetrievalFilters:
    source_types = arguments.get("source_types", ())
    if not isinstance(source_types, (list, tuple)) or any(
        not isinstance(value, str) or not value.strip() for value in source_types
    ):
        raise ValueError("source_types must be a list of non-empty strings")
    if len(source_types) > 8:
        raise ValueError("source_types cannot contain more than 8 values")
    return RetrievalFilters(
        tuple(source_types),
        _time(arguments.get("occurred_after")),
        _time(arguments.get("occurred_before")),
    )


def _time(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("time filters must be ISO-8601 strings")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("time filters must include a timezone")
    return parsed


def _render(values: tuple[RetrievedChunk, ...]) -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "chunk_id": str(value.chunk_id),
            "source_ref": value.source_ref,
            "source_type": value.source_type,
            "source_version": value.source_version,
            "occurred_at": value.occurred_at.isoformat(),
            "content": value.content,
            "fusion_score": value.fusion_score,
        }
        for value in values
    )
