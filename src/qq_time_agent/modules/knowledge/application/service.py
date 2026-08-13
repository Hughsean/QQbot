"""Versioned source indexing with local embedding contract validation."""

from uuid import uuid4

from qq_time_agent.modules.embeddings.contracts import EmbeddingPort
from qq_time_agent.modules.knowledge.application.ports import (
    IndexedChunk,
    IndexedSource,
    KnowledgeRepository,
)
from qq_time_agent.modules.knowledge.contracts import (
    IndexResult,
    SourceMetadata,
    build_index_version,
)
from qq_time_agent.modules.knowledge.domain.chunking import CHUNKER_VERSION, clean_and_chunk


class KnowledgeIndexService:
    def __init__(
        self,
        repository: KnowledgeRepository,
        embeddings: EmbeddingPort,
        model_id: str,
        dimensions: int,
        index_version: str,
    ) -> None:
        self._repository = repository
        self._embeddings = embeddings
        self._model_id = model_id
        self._dimensions = dimensions
        self._index_version = index_version

    async def upsert_source(
        self,
        source_ref: str,
        source_version: str,
        normalized_content: str,
        metadata: SourceMetadata,
    ) -> IndexResult:
        _validate_source(source_ref, source_version, metadata)
        drafts = clean_and_chunk(normalized_content)
        batch = await self._embeddings.embed(
            tuple(value.content for value in drafts), self._model_id, self._dimensions
        )
        if batch.model_id != self._model_id or batch.dimensions != self._dimensions:
            raise ValueError("Embedding result does not match active Knowledge index")
        source = IndexedSource(
            uuid4(),
            source_ref,
            metadata.source_type,
            source_version,
            metadata.occurred_at,
            metadata.trust_level,
            metadata.attributes,
            CHUNKER_VERSION,
            build_index_version(
                self._index_version,
                batch.model_id,
                batch.model_digest,
                batch.dimensions,
                chunker_version=CHUNKER_VERSION,
            ),
            batch.model_id,
            batch.model_digest,
            batch.dimensions,
            tuple(
                IndexedChunk(uuid4(), draft.ordinal, draft.content, draft.content_hash, vector)
                for draft, vector in zip(drafts, batch.vectors, strict=True)
            ),
        )
        stored = await self._repository.replace_active(source)
        return IndexResult(
            stored.source_id,
            stored.source_ref,
            stored.source_version,
            len(stored.chunks),
            stored.index_version,
        )

    async def delete_source(self, source_ref: str) -> int:
        if not source_ref.strip():
            raise ValueError("source_ref is required")
        return await self._repository.delete_source(source_ref)


def _validate_source(source_ref: str, source_version: str, metadata: SourceMetadata) -> None:
    if not source_ref.strip() or not source_version.strip():
        raise ValueError("Knowledge source reference and version are required")
    if metadata.source_type not in {"MICROSOFT_MAIL", "QQ_FORWARD", "OWNER_NOTE"}:
        raise ValueError("Knowledge source type is not indexable")
    if metadata.trust_level != "T2":
        raise ValueError("Knowledge content must remain T2")
    if metadata.occurred_at.tzinfo is None or metadata.occurred_at.utcoffset() is None:
        raise ValueError("Knowledge source time must be timezone-aware")
