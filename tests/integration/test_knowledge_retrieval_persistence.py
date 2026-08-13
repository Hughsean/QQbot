from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from qq_time_agent.adapters.outbound.persistence.database import create_database_engine
from qq_time_agent.bootstrap.settings import load_runtime_config
from qq_time_agent.modules.knowledge.application.ports import IndexedChunk, IndexedSource
from qq_time_agent.modules.knowledge.infrastructure.repository import SqlKnowledgeRepository
from qq_time_agent.modules.knowledge.infrastructure.tables import KnowledgeSourceRow

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest_asyncio.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    value = create_database_engine(load_runtime_config().database)
    yield value
    await value.dispose()


def _source(
    source_ref: str,
    version: str,
    content: str,
    vector: tuple[float, ...],
    occurred_at: datetime,
) -> IndexedSource:
    return IndexedSource(
        uuid4(),
        source_ref,
        "OWNER_NOTE",
        version,
        occurred_at,
        "T2",
        {"subject": "synthetic"},
        "deterministic-v1",
        "integration-v1",
        "test-model",
        "test-digest",
        1024,
        (IndexedChunk(uuid4(), 0, content, "hash", vector),),
    )


async def test_versioned_hybrid_search_filters_and_delete_are_atomic(
    engine: AsyncEngine,
) -> None:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    repository = SqlKnowledgeRepository(sessions)
    now = datetime(2026, 8, 20, tzinfo=UTC)
    source_ref = f"owner-note:integration:{uuid4()}"
    vector = (1.0,) + (0.0,) * 1023
    first = _source(source_ref, "v1", "星河项目报价截止周五", vector, now)
    stored = await repository.replace_active(first)
    repeated = await repository.replace_active(_source(source_ref, "v1", "不应覆盖", vector, now))
    assert repeated.source_id == stored.source_id
    assert repeated.chunks[0].content == "星河项目报价截止周五"

    vector_results = await repository.search_vector(
        vector,
        "integration-v1",
        "test-model",
        "test-digest",
        1024,
        ("OWNER_NOTE",),
        now - timedelta(days=1),
        now + timedelta(days=1),
        10,
    )
    lexical = await repository.search_lexical(
        "星河项目报价",
        "integration-v1",
        ("OWNER_NOTE",),
        None,
        None,
        10,
    )
    assert source_ref in {item.source_ref for item in vector_results}
    assert source_ref in {item.source_ref for item in lexical}
    assert (
        await repository.search_vector(
            vector,
            "integration-v1",
            "test-model",
            "wrong-digest",
            1024,
            (),
            None,
            None,
            10,
        )
        == ()
    )

    replacement = await repository.replace_active(
        _source(source_ref, "v2", "星河项目已完成", vector, now)
    )
    assert replacement.source_version == "v2"
    lexical = await repository.search_lexical("已完成", "integration-v1", (), None, None, 10)
    assert {item.source_version for item in lexical if item.source_ref == source_ref} == {"v2"}

    assert await repository.delete_source(source_ref) == 2
    after_delete = await repository.search_lexical("星河项目", "integration-v1", (), None, None, 30)
    assert source_ref not in {item.source_ref for item in after_delete}
    async with sessions() as session:
        assert await session.get(KnowledgeSourceRow, first.source_id) is None
        hnsw = await session.scalar(
            text("SELECT indexname FROM pg_indexes WHERE indexname='ix_knowledge_embedding_hnsw'")
        )
        trgm_index = await session.scalar(
            text(
                "SELECT indexname FROM pg_indexes WHERE indexname='ix_knowledge_chunk_content_trgm'"
            )
        )
        trgm_extension = await session.scalar(
            text("SELECT extversion FROM pg_extension WHERE extname='pg_trgm'")
        )
        assert hnsw and trgm_index and trgm_extension

    async with sessions.begin() as session:
        await session.execute(
            delete(KnowledgeSourceRow).where(KnowledgeSourceRow.source_ref == source_ref)
        )
