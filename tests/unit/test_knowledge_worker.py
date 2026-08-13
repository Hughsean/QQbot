from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from qq_time_agent.adapters.inbound.workers.knowledge import KnowledgeIndexJobHandler
from qq_time_agent.adapters.inbound.workers.knowledge_schedule import KnowledgeIndexScheduler
from qq_time_agent.contracts.jobs import JobLease, JobRequest
from qq_time_agent.modules.inbox.contracts import InboxContentView, InboxSourceView
from qq_time_agent.modules.knowledge.contracts import IndexResult, SourceMetadata
from qq_time_agent.modules.normalization.contracts import NormalizedContentView

NOW = datetime(2026, 8, 20, tzinfo=UTC)
ITEM_ID = uuid4()


@dataclass
class Sources:
    deleted: bool = False
    source_ref: str = "mail:connection:mail-1"

    async def get_source(self, inbox_item_id: UUID) -> InboxSourceView | None:
        assert inbox_item_id == ITEM_ID
        return InboxSourceView(
            ITEM_ID,
            "MICROSOFT_MAIL",
            "mail-1",
            None,
            "a***@example.com",
            "项目星河",
            NOW,
            "COMPLETED",
            self.deleted,
            self.source_ref,
        )


@dataclass
class Content:
    async def get_content(self, inbox_item_id: UUID) -> InboxContentView | None:
        return InboxContentView(
            inbox_item_id,
            "项目星河",
            "报价截止周五",
            None,
            "text/plain",
            NOW,
            "mail:connection:mail-1",
            "hash-1",
            None,
        )


@dataclass
class Normalized:
    async def get(self, inbox_item_id: UUID) -> NormalizedContentView | None:
        return NormalizedContentView(inbox_item_id, "项目星河", "报价截止周五", "hash-1", "v1")


@dataclass
class Knowledge:
    indexed: list[tuple[str, str, str, SourceMetadata]] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)

    async def upsert_source(
        self, source_ref: str, source_version: str, content: str, metadata: SourceMetadata
    ) -> IndexResult:
        self.indexed.append((source_ref, source_version, content, metadata))
        return IndexResult(uuid4(), source_ref, source_version, 1, "v1")

    async def delete_source(self, source_ref: str) -> int:
        self.deleted.append(source_ref)
        return 1


@dataclass
class Query:
    async def list_knowledge_source_ids(
        self, limit: int, after_id: UUID | None = None
    ) -> tuple[UUID, ...]:
        return (ITEM_ID,)


@dataclass
class Queue:
    values: list[JobRequest] = field(default_factory=list)

    async def enqueue(self, request: JobRequest) -> UUID:
        self.values.append(request)
        return uuid4()


@dataclass
class Clock:
    def now(self) -> datetime:
        return NOW


def _job() -> JobLease:
    return JobLease(uuid4(), "knowledge-index", {"inbox_item_id": str(ITEM_ID)}, "w", 1, 3)


@pytest.mark.asyncio
async def test_worker_indexes_traceable_t2_normalized_source() -> None:
    knowledge = Knowledge()
    await KnowledgeIndexJobHandler(Content(), Sources(), Normalized(), knowledge)(_job())
    source_ref, version, content, metadata = knowledge.indexed[0]
    assert source_ref == "mail:connection:mail-1" and version == "hash-1"
    assert content == "项目星河\n报价截止周五"
    assert metadata.trust_level == "T2" and metadata.attributes["sender"].endswith("example.com")


@pytest.mark.asyncio
async def test_worker_propagates_delete_without_reindexing() -> None:
    knowledge = Knowledge()
    await KnowledgeIndexJobHandler(Content(), Sources(True), Normalized(), knowledge)(_job())
    assert knowledge.deleted == ["mail:connection:mail-1"]
    assert knowledge.indexed == []


@pytest.mark.asyncio
async def test_scheduler_uses_content_version_and_deleted_tombstone_key() -> None:
    queue = Queue()
    await KnowledgeIndexScheduler(
        Query(),
        Content(),
        Sources(),
        queue,  # type: ignore[arg-type]
        Clock(),
    ).enqueue_due()
    assert queue.values[0].idempotency_key.startswith("knowledge:v1:")
    assert len(queue.values[0].idempotency_key) < 200
    deleted = Queue()
    await KnowledgeIndexScheduler(
        Query(),
        Content(),
        Sources(True),
        deleted,  # type: ignore[arg-type]
        Clock(),
    ).enqueue_due()
    assert deleted.values[0].idempotency_key != queue.values[0].idempotency_key


@pytest.mark.asyncio
async def test_scheduler_bounds_idempotency_key_for_long_provider_identifiers() -> None:
    queue = Queue()
    await KnowledgeIndexScheduler(
        Query(),
        Content(),
        Sources(source_ref=f"mail:connection:{'x' * 500}"),
        queue,  # type: ignore[arg-type]
        Clock(),
    ).enqueue_due()
    assert len(queue.values[0].idempotency_key) < 200
