"""Stage 7 versioned Knowledge chunks and pgvector retrieval.

Revision ID: 0007_knowledge_retrieval
Revises: 0006_actions_reminders
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0007_knowledge_retrieval"
down_revision: str | None = "0006_actions_reminders"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_table(
        "knowledge_sources",
        sa.Column("source_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source_ref", sa.String(512), nullable=False),
        sa.Column("source_type", sa.String(40), nullable=False),
        sa.Column("source_version", sa.String(128), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("trust_level", sa.String(10), nullable=False),
        sa.Column("attributes", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.UniqueConstraint("source_ref", "source_version", name="uq_knowledge_source_version"),
    )
    op.create_index(
        "ix_knowledge_source_filter",
        "knowledge_sources",
        ["status", "source_type", "occurred_at"],
    )
    op.create_table(
        "knowledge_chunks",
        sa.Column("chunk_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("knowledge_sources.source_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("chunker_version", sa.String(80), nullable=False),
        sa.Column("index_version", sa.String(128), nullable=False),
        sa.UniqueConstraint("source_id", "ordinal", name="uq_knowledge_chunk_ordinal"),
    )
    op.create_index("ix_knowledge_chunk_index", "knowledge_chunks", ["index_version"])
    op.create_index(
        "ix_knowledge_chunk_content_trgm",
        "knowledge_chunks",
        ["content"],
        postgresql_using="gin",
        postgresql_ops={"content": "gin_trgm_ops"},
    )
    op.create_table(
        "knowledge_embeddings",
        sa.Column(
            "chunk_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("knowledge_chunks.chunk_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("model_id", sa.String(200), nullable=False),
        sa.Column("model_digest", sa.String(256), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("embedding", Vector(1024), nullable=False),
    )
    op.create_index(
        "ix_knowledge_embedding_hnsw",
        "knowledge_embeddings",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_knowledge_embedding_hnsw", table_name="knowledge_embeddings")
    op.drop_table("knowledge_embeddings")
    op.drop_index("ix_knowledge_chunk_content_trgm", table_name="knowledge_chunks")
    op.drop_index("ix_knowledge_chunk_index", table_name="knowledge_chunks")
    op.drop_table("knowledge_chunks")
    op.drop_index("ix_knowledge_source_filter", table_name="knowledge_sources")
    op.drop_table("knowledge_sources")
