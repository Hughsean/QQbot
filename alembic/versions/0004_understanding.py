"""Stage 4 AI metadata, candidates, and bounded workflow checkpoints.

Revision ID: 0004_understanding
Revises: 0003_mail_inbox
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_understanding"
down_revision: str | None = "0003_mail_inbox"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_gateway_invocations",
        sa.Column("invocation_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("use_case", sa.String(80), nullable=False),
        sa.Column("prompt_version", sa.String(80), nullable=False),
        sa.Column("route", sa.String(20), nullable=False),
        sa.Column("model", sa.String(120)),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("failure_class", sa.String(80)),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
    )
    op.create_table(
        "understanding_candidates",
        sa.Column("candidate_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("inbox_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True)),
        sa.Column("ends_at", sa.DateTime(timezone=True)),
        sa.Column("deadline", sa.DateTime(timezone=True)),
        sa.Column("timezone", sa.String(80), nullable=False),
        sa.Column("location", sa.String(300)),
        sa.Column("participants", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("estimated_duration_minutes", sa.Integer()),
        sa.Column("priority", sa.String(20)),
        sa.Column("allowed_windows", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("assumptions", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("evidence", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("source_refs", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.UniqueConstraint("inbox_item_id", name="uq_understanding_candidate_inbox"),
    )
    op.create_table(
        "workflow_understanding_checkpoints",
        sa.Column("inbox_item_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("phase", sa.String(20), nullable=False),
        sa.Column("result_kind", sa.String(20)),
        sa.Column("candidate_id", postgresql.UUID(as_uuid=True)),
        sa.Column("confidence", sa.Float()),
        sa.Column("review_reason", sa.String(120)),
        sa.Column("model_calls", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE inbox_items SET status = 'NORMALIZED', failure_class = NULL, "
            "version = version + 1 WHERE status IN "
            "('UNDERSTOOD', 'IGNORED', 'NEEDS_REVIEW')"
        )
    )
    op.drop_table("workflow_understanding_checkpoints")
    op.drop_table("understanding_candidates")
    op.drop_table("ai_gateway_invocations")
