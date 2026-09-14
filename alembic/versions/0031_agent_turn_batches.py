"""Add durable QQ conversation turn batches.

Revision ID: 0031_agent_turn_batches
Revises: 0030_todo_completion_gate
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0031_agent_turn_batches"
down_revision: str | None = "0030_todo_completion_gate"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_runs",
        sa.Column(
            "source_refs",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.alter_column("agent_runs", "source_refs", server_default=None)
    op.create_table(
        "agent_turn_batches",
        sa.Column("turn_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(length=120), nullable=False),
        sa.Column("conversation_key_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("message_count", sa.Integer(), nullable=False),
        sa.Column("content_chars", sa.Integer(), nullable=False),
        sa.Column("ready_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("hard_deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_owner", sa.String(length=160), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_class", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('OPEN', 'LEASED', 'COMPLETED', 'FAILED')",
            name="ck_agent_turn_batches_status",
        ),
        sa.CheckConstraint(
            "generation >= 1 AND message_count >= 1 AND content_chars >= 0",
            name="ck_agent_turn_batches_counts",
        ),
        sa.PrimaryKeyConstraint("turn_id"),
    )
    op.create_index(
        "ix_agent_turn_batches_conversation_status",
        "agent_turn_batches",
        ["conversation_key_hash", "status", "created_at"],
    )
    op.create_table(
        "agent_turn_segments",
        sa.Column("turn_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("inbox_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_type", sa.String(length=40), nullable=False),
        sa.Column("trust_level", sa.String(length=10), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider_sequence", sa.BigInteger(), nullable=True),
        sa.Column("reference_hash", sa.String(length=64), nullable=True),
        sa.Column("content_chars", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "position >= 1 AND content_chars >= 0", name="ck_agent_turn_segments_size"
        ),
        sa.ForeignKeyConstraint(["turn_id"], ["agent_turn_batches.turn_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("turn_id", "position"),
        sa.UniqueConstraint("inbox_item_id", name="uq_agent_turn_segments_inbox_item"),
    )


def downgrade() -> None:
    op.drop_table("agent_turn_segments")
    op.drop_index("ix_agent_turn_batches_conversation_status", table_name="agent_turn_batches")
    op.drop_table("agent_turn_batches")
    op.drop_column("agent_runs", "source_refs")
