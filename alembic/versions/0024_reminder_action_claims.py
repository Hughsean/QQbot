"""Add mutually exclusive Reminder action claims."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024_reminder_action_claims"
down_revision: str | None = "0023_agent_run_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "notifications_reminder_action_tokens",
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "notifications_reminder_action_tokens",
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "notifications_reminder_action_tokens",
        sa.Column("outcome", sa.String(40), nullable=True),
    )
    op.create_index(
        "uq_notifications_reminder_action_tokens_claim",
        "notifications_reminder_action_tokens",
        ["owner_id", "reminder_id", "occurrence"],
        unique=True,
        postgresql_where=sa.text("claimed_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_notifications_reminder_action_tokens_claim",
        table_name="notifications_reminder_action_tokens",
    )
    op.drop_column("notifications_reminder_action_tokens", "outcome")
    op.drop_column("notifications_reminder_action_tokens", "resolved_at")
    op.drop_column("notifications_reminder_action_tokens", "claimed_at")
