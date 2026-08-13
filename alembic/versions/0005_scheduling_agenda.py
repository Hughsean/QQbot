"""Stage 5 authoritative Agenda and side-effect-free Scheduling Proposals.

Revision ID: 0005_scheduling_agenda
Revises: 0004_understanding
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_scheduling_agenda"
down_revision: str | None = "0004_understanding"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "identity_user_preferences",
        sa.Column("user_id", sa.String(120), primary_key=True),
        sa.Column("timezone", sa.String(80), nullable=False),
        sa.Column("work_start", sa.Time(), nullable=False),
        sa.Column("work_end", sa.Time(), nullable=False),
        sa.Column("lunch_start", sa.Time(), nullable=False),
        sa.Column("lunch_end", sa.Time(), nullable=False),
        sa.Column("working_weekdays", postgresql.ARRAY(sa.Integer()), nullable=False),
        sa.Column("default_event_minutes", sa.Integer(), nullable=False),
        sa.Column("default_task_minutes", sa.Integer(), nullable=False),
    )
    op.create_table(
        "agenda_entries",
        sa.Column("agenda_entry_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("action_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("timezone", sa.String(80), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("source_refs", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("proposal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.UniqueConstraint("idempotency_key", name="uq_agenda_idempotency"),
    )
    op.create_index(
        "ix_agenda_active_range",
        "agenda_entries",
        ["status", "starts_at", "ends_at"],
    )
    op.create_table(
        "scheduling_proposals",
        sa.Column("proposal_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.String(120), nullable=False),
        sa.Column("candidate_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("candidate_kind", sa.String(20), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("recommended_slot", postgresql.JSONB()),
        sa.Column("alternative_slots", postgresql.JSONB(), nullable=False),
        sa.Column("conflicts", postgresql.JSONB(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("assumptions", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("source_refs", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("constraint_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.UniqueConstraint("candidate_id", name="uq_scheduling_proposal_candidate"),
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE inbox_items SET status = 'UNDERSTOOD', failure_class = NULL, "
            "version = version + 1 WHERE status = 'PROPOSED'"
        )
    )
    op.execute(
        sa.text(
            "DELETE FROM platform_jobs WHERE kind = 'scheduling-propose' "
            "OR idempotency_key LIKE 'scheduling:%'"
        )
    )
    op.drop_table("scheduling_proposals")
    op.drop_index("ix_agenda_active_range", table_name="agenda_entries")
    op.drop_table("agenda_entries")
    op.execute(sa.text("DROP TABLE IF EXISTS identity_user_preferences"))
