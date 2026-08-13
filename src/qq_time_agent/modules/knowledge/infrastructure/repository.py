"""Atomic PostgreSQL Knowledge indexing, filtered vector and lexical search."""

from datetime import datetime

from sqlalchemy import ColumnElement, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from qq_time_agent.modules.knowledge.application.ports import IndexedChunk, IndexedSource
from qq_time_agent.modules.knowledge.contracts import KnowledgeSearchCandidate
from qq_time_agent.modules.knowledge.infrastructure.tables import (
    KnowledgeChunkRow,
    KnowledgeEmbeddingRow,
    KnowledgeSourceRow,
)


class SqlKnowledgeRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def replace_active(self, value: IndexedSource) -> IndexedSource:
        async with self._sessions.begin() as session:
            existing = await session.scalar(
                select(KnowledgeSourceRow).where(
                    KnowledgeSourceRow.source_ref == value.source_ref,
                    KnowledgeSourceRow.source_version == value.source_version,
                )
            )
            await session.execute(
                update(KnowledgeSourceRow)
                .where(
                    KnowledgeSourceRow.source_ref == value.source_ref,
                    KnowledgeSourceRow.status == "ACTIVE",
                )
                .values(status="SUPERSEDED")
            )
            if existing is not None:
                existing.status = "ACTIVE"
                return await self._load(session, existing)
            await self._insert(session, value)
        return value

    async def delete_source(self, source_ref: str) -> int:
        async with self._sessions.begin() as session:
            ids = tuple(
                await session.scalars(
                    select(KnowledgeSourceRow.source_id).where(
                        KnowledgeSourceRow.source_ref == source_ref,
                        KnowledgeSourceRow.status != "DELETED",
                    )
                )
            )
            if not ids:
                return 0
            await session.execute(
                update(KnowledgeSourceRow)
                .where(KnowledgeSourceRow.source_id.in_(ids))
                .values(status="DELETED")
            )
            await session.execute(
                delete(KnowledgeSourceRow).where(KnowledgeSourceRow.source_id.in_(ids))
            )
            return len(ids)

    async def search_vector(
        self,
        vector: tuple[float, ...],
        index_version: str,
        model_id: str,
        model_digest: str,
        dimensions: int,
        source_types: tuple[str, ...],
        occurred_after: datetime | None,
        occurred_before: datetime | None,
        limit: int,
    ) -> tuple[KnowledgeSearchCandidate, ...]:
        distance = KnowledgeEmbeddingRow.embedding.cosine_distance(list(vector))
        statement = (
            select(KnowledgeChunkRow, KnowledgeSourceRow, distance.label("distance"))
            .join(KnowledgeSourceRow, KnowledgeSourceRow.source_id == KnowledgeChunkRow.source_id)
            .join(
                KnowledgeEmbeddingRow,
                KnowledgeEmbeddingRow.chunk_id == KnowledgeChunkRow.chunk_id,
            )
            .where(
                *_filters(index_version, source_types, occurred_after, occurred_before),
                KnowledgeEmbeddingRow.model_id == model_id,
                KnowledgeEmbeddingRow.model_digest == model_digest,
                KnowledgeEmbeddingRow.dimensions == dimensions,
            )
            .order_by(distance, KnowledgeChunkRow.chunk_id)
            .limit(limit)
        )
        async with self._sessions() as session:
            rows = (await session.execute(statement)).all()
        return tuple(_candidate(chunk, source, float(score), None) for chunk, source, score in rows)

    async def search_lexical(
        self,
        query: str,
        index_version: str,
        source_types: tuple[str, ...],
        occurred_after: datetime | None,
        occurred_before: datetime | None,
        limit: int,
    ) -> tuple[KnowledgeSearchCandidate, ...]:
        score = func.similarity(KnowledgeChunkRow.content, query)
        statement = (
            select(KnowledgeChunkRow, KnowledgeSourceRow, score.label("score"))
            .join(KnowledgeSourceRow, KnowledgeSourceRow.source_id == KnowledgeChunkRow.source_id)
            .where(
                *_filters(index_version, source_types, occurred_after, occurred_before),
                score > 0,
            )
            .order_by(score.desc(), KnowledgeChunkRow.chunk_id)
            .limit(limit)
        )
        async with self._sessions() as session:
            rows = (await session.execute(statement)).all()
        return tuple(_candidate(chunk, source, None, float(value)) for chunk, source, value in rows)

    async def _insert(self, session: AsyncSession, value: IndexedSource) -> None:
        session.add(
            KnowledgeSourceRow(
                source_id=value.source_id,
                source_ref=value.source_ref,
                source_type=value.source_type,
                source_version=value.source_version,
                occurred_at=value.occurred_at,
                trust_level=value.trust_level,
                attributes=value.attributes,
                status="ACTIVE",
            )
        )
        await session.flush()
        for chunk in value.chunks:
            session.add(
                KnowledgeChunkRow(
                    chunk_id=chunk.chunk_id,
                    source_id=value.source_id,
                    ordinal=chunk.ordinal,
                    content=chunk.content,
                    content_hash=chunk.content_hash,
                    chunker_version=value.chunker_version,
                    index_version=value.index_version,
                )
            )
        await session.flush()
        for chunk in value.chunks:
            session.add(
                KnowledgeEmbeddingRow(
                    chunk_id=chunk.chunk_id,
                    model_id=value.model_id,
                    model_digest=value.model_digest,
                    dimensions=value.dimensions,
                    embedding=list(chunk.embedding),
                )
            )

    async def _load(self, session: AsyncSession, source: KnowledgeSourceRow) -> IndexedSource:
        rows = (
            await session.execute(
                select(KnowledgeChunkRow, KnowledgeEmbeddingRow)
                .join(
                    KnowledgeEmbeddingRow,
                    KnowledgeEmbeddingRow.chunk_id == KnowledgeChunkRow.chunk_id,
                )
                .where(KnowledgeChunkRow.source_id == source.source_id)
                .order_by(KnowledgeChunkRow.ordinal)
            )
        ).all()
        if not rows:
            raise RuntimeError("Stored Knowledge source has no chunks")
        chunks = tuple(
            IndexedChunk(
                chunk.chunk_id,
                chunk.ordinal,
                chunk.content,
                chunk.content_hash,
                tuple(float(value) for value in embedding.embedding),
            )
            for chunk, embedding in rows
        )
        first_chunk, first_embedding = rows[0]
        return IndexedSource(
            source.source_id,
            source.source_ref,
            source.source_type,
            source.source_version,
            source.occurred_at,
            source.trust_level,
            source.attributes,
            first_chunk.chunker_version,
            first_chunk.index_version,
            first_embedding.model_id,
            first_embedding.model_digest,
            first_embedding.dimensions,
            chunks,
        )


def _filters(
    index_version: str,
    source_types: tuple[str, ...],
    occurred_after: datetime | None,
    occurred_before: datetime | None,
) -> list[ColumnElement[bool]]:
    values: list[ColumnElement[bool]] = [
        KnowledgeSourceRow.status == "ACTIVE",
        KnowledgeChunkRow.index_version == index_version,
    ]
    if source_types:
        values.append(KnowledgeSourceRow.source_type.in_(source_types))
    if occurred_after is not None:
        values.append(KnowledgeSourceRow.occurred_at >= occurred_after)
    if occurred_before is not None:
        values.append(KnowledgeSourceRow.occurred_at <= occurred_before)
    return values


def _candidate(
    chunk: KnowledgeChunkRow,
    source: KnowledgeSourceRow,
    vector_distance: float | None,
    lexical_score: float | None,
) -> KnowledgeSearchCandidate:
    return KnowledgeSearchCandidate(
        chunk.chunk_id,
        source.source_ref,
        source.source_type,
        source.source_version,
        source.occurred_at,
        chunk.content,
        chunk.ordinal,
        vector_distance,
        lexical_score,
    )
