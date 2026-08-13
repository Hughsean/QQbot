"""Idempotent discovery of Inbox sources eligible for Knowledge."""

import hashlib
from uuid import UUID

from qq_time_agent.contracts.clock import Clock
from qq_time_agent.contracts.jobs import JobQueue, JobRequest
from qq_time_agent.modules.inbox.contracts import (
    InboxContentPort,
    InboxKnowledgeQueryPort,
    InboxSourcePort,
)

KNOWLEDGE_JOB = "knowledge-index"
KNOWLEDGE_PIPELINE_VERSION = "v1"


class KnowledgeIndexScheduler:
    def __init__(
        self,
        query: InboxKnowledgeQueryPort,
        content: InboxContentPort,
        sources: InboxSourcePort,
        queue: JobQueue,
        clock: Clock,
        batch_size: int = 50,
    ) -> None:
        if batch_size < 1 or batch_size > 100:
            raise ValueError("Knowledge scheduler batch must be between 1 and 100")
        self._query = query
        self._content = content
        self._sources = sources
        self._queue = queue
        self._clock = clock
        self._batch_size = batch_size
        self._after_id: UUID | None = None

    async def enqueue_due(self) -> None:
        values = await self._query.list_knowledge_source_ids(self._batch_size, self._after_id)
        if not values and self._after_id is not None:
            self._after_id = None
            values = await self._query.list_knowledge_source_ids(self._batch_size, None)
        for inbox_item_id in values:
            source = await self._sources.get_source(inbox_item_id)
            if source is None or source.source_ref is None:
                continue
            content = await self._content.get_content(inbox_item_id)
            version = "deleted" if source.deleted else _content_version(content)
            await self._queue.enqueue(
                JobRequest(
                    KNOWLEDGE_JOB,
                    {"inbox_item_id": str(inbox_item_id)},
                    _idempotency_key(source.source_ref, version),
                    self._clock.now(),
                    max_attempts=3,
                )
            )
        if values:
            self._after_id = values[-1]


def _content_version(content: object) -> str:
    value = getattr(content, "content_hash", None)
    if not isinstance(value, str) or not value:
        return "not-ready"
    return value


def _idempotency_key(source_ref: str, content_version: str) -> str:
    material = f"{source_ref}\0{content_version}\0{KNOWLEDGE_PIPELINE_VERSION}".encode()
    digest = hashlib.sha256(material).hexdigest()
    return f"knowledge:{KNOWLEDGE_PIPELINE_VERSION}:{digest}"
