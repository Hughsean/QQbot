"""Create Reminder interaction token persistence."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022_reminder_action_tokens"
down_revision: str | None = "0021_agent_run_execution_fencing"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "notifications_reminder_action_tokens",
        sa.Column("token_hash", sa.String(128), primary_key=True),
        sa.Column("owner_id", sa.String(120), nullable=False),
        sa.Column("reminder_id", sa.UUID(), nullable=False),
        sa.Column("agenda_entry_id", sa.UUID(), nullable=False),
        sa.Column("agenda_entry_version", sa.Integer(), nullable=False),
        sa.Column("occurrence", sa.Integer(), nullable=False),
        sa.Column("action_type", sa.String(80), nullable=False),
        sa.Column("action_value", sa.String(80), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_notifications_reminder_action_tokens_expiry",
        "notifications_reminder_action_tokens",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_notifications_reminder_action_tokens_expiry",
        table_name="notifications_reminder_action_tokens",
    )
    op.drop_table("notifications_reminder_action_tokens")
