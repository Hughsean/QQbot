"""Stage 6 confirmed Actions, durable Reminders and QQ Notifications.

Revision ID: 0006_actions_reminders
Revises: 0005_scheduling_agenda
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_actions_reminders"
down_revision: str | None = "0005_scheduling_agenda"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agenda_entries",
        sa.Column("last_operation_key", sa.String(200), nullable=False, server_default="created"),
    )
    op.alter_column("agenda_entries", "last_operation_key", server_default=None)
    op.create_table(
        "actions_requests",
        sa.Column("action_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.String(120), nullable=False),
        sa.Column("action_type", sa.String(30), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("proposal_id", postgresql.UUID(as_uuid=True)),
        sa.Column("proposal_version", sa.Integer()),
        sa.Column("agenda_entry_id", postgresql.UUID(as_uuid=True)),
        sa.Column("agenda_entry_version", sa.Integer()),
        sa.Column("reminder_id", postgresql.UUID(as_uuid=True)),
        sa.Column("failure_class", sa.String(120)),
        sa.UniqueConstraint("idempotency_key", name="uq_actions_idempotency"),
    )
    op.create_table(
        "reminders_items",
        sa.Column("reminder_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("agenda_entry_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agenda_entry_version", sa.Integer(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("lease_owner", sa.String(120)),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("delivery_ref", sa.String(512)),
        sa.Column("failure_class", sa.Text()),
        sa.Column("occurrence", sa.Integer(), nullable=False),
        sa.UniqueConstraint("idempotency_key", name="uq_reminders_idempotency"),
    )
    op.create_index("ix_reminders_due", "reminders_items", ["status", "due_at"])
    op.create_table(
        "notifications_deliveries",
        sa.Column("idempotency_key", sa.String(240), primary_key=True),
        sa.Column("delivery_id", sa.String(512), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("notifications_deliveries")
    op.drop_index("ix_reminders_due", table_name="reminders_items")
    op.drop_table("reminders_items")
    op.drop_table("actions_requests")
    op.drop_column("agenda_entries", "last_operation_key")
