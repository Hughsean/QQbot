"""Owner mail notification rules for deterministic delivery resolution.

Revision ID: 0025_identity_mail_rules
Revises: 0024_reminder_action_claims
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025_identity_mail_rules"
down_revision: str | None = "0024_reminder_action_claims"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "identity_mail_rules",
        sa.Column("rule_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.String(120), nullable=False),
        sa.Column("match_field", sa.String(20), nullable=False),
        sa.Column("pattern", sa.String(240), nullable=False),
        sa.Column("normalized_pattern", sa.String(240), nullable=False),
        sa.Column("action", sa.String(10), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("rule_id"),
        sa.UniqueConstraint("user_id", "match_field", "normalized_pattern"),
        sa.CheckConstraint(
            "match_field IN ('SENDER', 'SUBJECT')", name="ck_mail_rules_match_field"
        ),
        sa.CheckConstraint("action IN ('NOTIFY', 'HOLD')", name="ck_mail_rules_action"),
    )
    op.create_index(
        "ix_identity_mail_rules_user",
        "identity_mail_rules",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_identity_mail_rules_user", table_name="identity_mail_rules")
    op.drop_table("identity_mail_rules")
