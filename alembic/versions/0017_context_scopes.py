"""Add explicit Conversation and EventCase context scopes."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0017_context_scopes"
down_revision: str | None = "0016_agent_actions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_conversations",
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(120), nullable=False),
        sa.Column("channel", sa.String(40), nullable=False),
        sa.Column("conversation_key", sa.String(512), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("conversation_id"),
        sa.UniqueConstraint(
            "user_id", "channel", "conversation_key", name="uq_agent_conversation_scope"
        ),
    )
    op.create_table(
        "agent_event_cases",
        sa.Column("event_case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(120), nullable=False),
        sa.Column("event_key", sa.String(512), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("event_case_id"),
        sa.UniqueConstraint("user_id", "event_key", name="uq_agent_event_scope"),
    )
    op.create_table(
        "agent_context_items",
        sa.Column("scope_type", sa.String(20), nullable=False),
        sa.Column("scope_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("inbox_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("scope_type", "scope_id", "inbox_item_id"),
    )
    op.create_index(
        "ix_agent_context_items_scope_time",
        "agent_context_items",
        ["scope_type", "scope_id", "occurred_at"],
    )
    op.add_column(
        "agent_runs", sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.add_column(
        "agent_runs", sa.Column("event_case_id", postgresql.UUID(as_uuid=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("agent_runs", "event_case_id")
    op.drop_column("agent_runs", "conversation_id")
    op.drop_index("ix_agent_context_items_scope_time", table_name="agent_context_items")
    op.drop_table("agent_context_items")
    op.drop_table("agent_event_cases")
    op.drop_table("agent_conversations")
