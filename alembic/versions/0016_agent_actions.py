"""Persist calendar operation payloads and Agent runs."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016_agent_actions"
down_revision: str | None = "0015_notifications"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "actions_requests", sa.Column("operation_payload", postgresql.JSONB(), nullable=True)
    )
    op.create_table(
        "agent_runs",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("inbox_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(120), nullable=False),
        sa.Column("source_type", sa.String(40), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("step", sa.Integer(), nullable=False),
        sa.Column("observations", postgresql.JSONB(), nullable=False),
        sa.Column("final_content", sa.Text(), nullable=True),
        sa.Column("failure_class", sa.String(120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("run_id"),
        sa.UniqueConstraint("inbox_item_id", name="uq_agent_runs_inbox_item"),
    )
    op.create_index("ix_agent_runs_status_updated", "agent_runs", ["status", "updated_at"])
    op.create_table(
        "agent_tool_calls",
        sa.Column("call_id", sa.String(160), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tool_name", sa.String(120), nullable=False),
        sa.Column("arguments_hash", sa.String(128), nullable=False),
        sa.Column("observation", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("run_id", "call_id"),
    )


def downgrade() -> None:
    op.drop_table("agent_tool_calls")
    op.drop_index("ix_agent_runs_status_updated", table_name="agent_runs")
    op.drop_table("agent_runs")
    op.drop_column("actions_requests", "operation_payload")
