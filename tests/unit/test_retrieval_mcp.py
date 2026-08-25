from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from qq_time_agent.modules.retrieval.application.mcp_tools import RagToolRegistry
from qq_time_agent.modules.retrieval.contracts import RetrievalFilters, RetrievedChunk


@dataclass
class Retrieval:
    async def retrieve(
        self, query: str, filters: RetrievalFilters, limit: int
    ) -> tuple[RetrievedChunk, ...]:
        del query, filters, limit
        return (
            RetrievedChunk(
                uuid4(),
                "mail:1",
                "MICROSOFT_MAIL",
                "v1",
                datetime(2026, 8, 20, tzinfo=UTC),
                "内容",
                0.1,
                0.8,
                0.02,
            ),
        )


@pytest.mark.asyncio
async def test_mcp_registry_is_owner_scoped_and_bounded() -> None:
    registry = RagToolRegistry(Retrieval())
    with pytest.raises(PermissionError):
        await registry.call("search_knowledge", "other", {"query": "q"})
    with pytest.raises(ValueError, match="between"):
        await registry.call("search_knowledge", "owner", {"query": "q", "limit": 31})
    result = await registry.call("search_knowledge", "owner", {"query": "q"})
    assert result[0]["source_ref"] == "mail:1"
