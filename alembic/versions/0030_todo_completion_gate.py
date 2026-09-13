"""Record reminder suppressions caused by verified task completion.

Revision ID: 0030_todo_completion_gate
Revises: 0029_task_projection
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0030_todo_completion_gate"
down_revision: str | None = "0029_task_projection"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "notifications_reminder_suppressions",
        sa.Column("idempotency_key", sa.String(length=240), nullable=False),
        sa.Column("reason", sa.String(length=80), nullable=False),
        sa.Column("suppressed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("idempotency_key"),
    )


def downgrade() -> None:
    op.drop_table("notifications_reminder_suppressions")
