"""Add the unified conversation event timeline and AgentRun snapshot columns.

Revision ID: 0027_conversation_events
Revises: 0026_effective_delivery
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0027_conversation_events"
down_revision: str | None = "0026_effective_delivery"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EVENT_TYPES = (
    "USER_MESSAGE",
    "AGENT_REPLY",
    "TOOL_CALL",
    "TOOL_RESULT",
    "MAIL_NOTIFICATION",
    "MAIL_DIGEST",
    "DAILY_DIGEST",
    "SYSTEM_RESULT",
)
_EVENT_TYPE_LIST = ", ".join(f"'{value}'" for value in _EVENT_TYPES)


def upgrade() -> None:
    op.create_table(
        "agent_conversation_sequence_counters",
        sa.Column("user_id", sa.String(120), nullable=False),
        sa.Column("last_sequence", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_table(
        "agent_conversation_events",
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scope_type", sa.String(20), nullable=False),
        sa.Column("scope_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(120), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_ref", sa.String(160), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("delivery_status", sa.String(16), nullable=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("inbox_item_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("notification_intent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("event_id"),
        sa.UniqueConstraint(
            "scope_type", "scope_id", "sequence", name="uq_agent_conversation_events_scope_sequence"
        ),
        sa.UniqueConstraint(
            "user_id", "sequence", name="uq_agent_conversation_events_user_sequence"
        ),
        sa.UniqueConstraint("idempotency_key", name="uq_agent_conversation_events_idempotency"),
        sa.CheckConstraint("sequence >= 1", name="ck_agent_conversation_events_sequence"),
        sa.CheckConstraint(
            "scope_type IN ('conversation', 'owner_timeline')",
            name="ck_agent_conversation_events_scope",
        ),
        sa.CheckConstraint(
            f"event_type IN ({_EVENT_TYPE_LIST})",
            name="ck_agent_conversation_events_type",
        ),
        sa.CheckConstraint(
            "role IN ('user', 'agent', 'tool', 'system')",
            name="ck_agent_conversation_events_role",
        ),
        sa.CheckConstraint(
            "delivery_status IS NULL OR delivery_status IN ('DELIVERED', 'FAILED')",
            name="ck_agent_conversation_events_delivery",
        ),
    )
    op.create_index(
        "ix_agent_conversation_events_scope_time",
        "agent_conversation_events",
        ["scope_type", "scope_id", "occurred_at"],
    )
    op.create_table(
        "agent_conversation_summaries",
        sa.Column("summary_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scope_type", sa.String(20), nullable=False),
        sa.Column("scope_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(120), nullable=False),
        sa.Column("summary_kind", sa.String(40), nullable=False),
        sa.Column("from_sequence", sa.Integer(), nullable=False),
        sa.Column("to_sequence", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("summary_id"),
        sa.UniqueConstraint(
            "scope_type",
            "scope_id",
            "from_sequence",
            "to_sequence",
            name="uq_agent_conversation_summaries_range",
        ),
        sa.CheckConstraint(
            "scope_type IN ('conversation', 'owner_timeline')",
            name="ck_agent_conversation_summaries_scope",
        ),
        sa.CheckConstraint(
            "from_sequence >= 1 AND to_sequence >= from_sequence",
            name="ck_agent_conversation_summaries_range",
        ),
    )
    op.create_index(
        "ix_agent_conversation_summaries_scope_to",
        "agent_conversation_summaries",
        ["scope_type", "scope_id", "to_sequence"],
    )
    op.add_column(
        "agent_runs", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("agent_runs", sa.Column("context_revision", sa.Integer(), nullable=True))
    op.add_column("agent_runs", sa.Column("context_max_sequence", sa.Integer(), nullable=True))
    op.add_column("agent_runs", sa.Column("context_hash", sa.String(64), nullable=True))
    op.create_index("ix_agent_runs_completed", "agent_runs", ["completed_at"])
    op.execute(
        "UPDATE agent_runs SET completed_at = updated_at "
        "WHERE status = 'COMPLETED' AND completed_at IS NULL"
    )


def downgrade() -> None:
    op.drop_index("ix_agent_runs_completed", table_name="agent_runs")
    op.drop_column("agent_runs", "context_hash")
    op.drop_column("agent_runs", "context_max_sequence")
    op.drop_column("agent_runs", "context_revision")
    op.drop_column("agent_runs", "completed_at")
    op.drop_index(
        "ix_agent_conversation_summaries_scope_to", table_name="agent_conversation_summaries"
    )
    op.drop_table("agent_conversation_summaries")
    op.drop_index(
        "ix_agent_conversation_events_scope_time", table_name="agent_conversation_events"
    )
    op.drop_table("agent_conversation_events")
    op.drop_table("agent_conversation_sequence_counters")
