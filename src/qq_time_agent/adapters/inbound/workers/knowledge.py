"""Thin source-propagation worker for the versioned Knowledge index."""

from uuid import UUID

from qq_time_agent.adapters.inbound.workers.runner import RetryableJobError
from qq_time_agent.contracts.jobs import JobLease
from qq_time_agent.modules.embeddings.contracts import EmbeddingError
from qq_time_agent.modules.inbox.contracts import InboxContentPort, InboxSourcePort
from qq_time_agent.modules.knowledge.contracts import KnowledgeIndexPort, SourceMetadata
from qq_time_agent.modules.normalization.contracts import NormalizedContentQueryPort


class KnowledgeIndexJobHandler:
    def __init__(
        self,
        inbox_content: InboxContentPort,
        inbox_sources: InboxSourcePort,
        normalized: NormalizedContentQueryPort,
        knowledge: KnowledgeIndexPort,
    ) -> None:
        self._inbox_content = inbox_content
        self._inbox_sources = inbox_sources
        self._normalized = normalized
        self._knowledge = knowledge

    async def __call__(self, job: JobLease) -> None:
        raw_id = job.payload.get("inbox_item_id")
        if not isinstance(raw_id, str):
            raise ValueError("Knowledge job inbox_item_id is required")
        inbox_item_id = UUID(raw_id)
        source = await self._inbox_sources.get_source(inbox_item_id)
        if source is None or source.source_ref is None:
            raise LookupError("Knowledge source does not exist")
        if source.deleted:
            await self._knowledge.delete_source(source.source_ref)
            return
        content = await self._inbox_content.get_content(inbox_item_id)
        normalized = await self._normalized.get(inbox_item_id)
        if content is None or normalized is None:
            raise LookupError("Knowledge source is not normalized")
        metadata = SourceMetadata(
            source.source_type,
            source.occurred_at,
            "T2",
            {"subject": normalized.subject, "sender": source.sender_mask},
        )
        try:
            await self._knowledge.upsert_source(
                source.source_ref,
                normalized.source_hash,
                _document(normalized.subject, normalized.body),
                metadata,
            )
        except EmbeddingError as exc:
            if exc.failure_class == "TransientProvider":
                raise RetryableJobError(exc.failure_class) from exc
            raise


def _document(subject: str, body: str) -> str:
    return "\n".join(value for value in (subject.strip(), body.strip()) if value)
