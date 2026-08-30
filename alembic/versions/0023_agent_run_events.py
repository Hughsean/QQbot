"""Add append-only AgentRun execution timeline."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0023_agent_run_events"
down_revision: str | None = "0022_reminder_action_tokens"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_run_events",
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("step", sa.Integer(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(32), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_class", sa.String(120), nullable=True),
        sa.Column("tool_name", sa.String(120), nullable=True),
        sa.Column("call_id", sa.String(160), nullable=True),
        sa.Column("invocation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("event_id"),
        sa.UniqueConstraint("run_id", "sequence", name="uq_agent_run_events_sequence"),
        sa.UniqueConstraint("run_id", "idempotency_key", name="uq_agent_run_events_idempotency"),
    )
    op.create_index(
        "ix_agent_run_events_run_time", "agent_run_events", ["run_id", "occurred_at"]
    )
    op.create_index("ix_agent_run_events_run_scope", "agent_run_events", ["run_id", "sequence"])


def downgrade() -> None:
    op.drop_index("ix_agent_run_events_run_scope", table_name="agent_run_events")
    op.drop_index("ix_agent_run_events_run_time", table_name="agent_run_events")
    op.drop_table("agent_run_events")
