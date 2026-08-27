"""Persist owner-declared forwarded group-chat display aliases.

Revision ID: 0020_owner_group_aliases
Revises: 0019_agent_scope_reply_indexes
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020_owner_group_aliases"
down_revision: str | None = "0019_agent_scope_reply_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "identity_owner_group_aliases",
        sa.Column("user_id", sa.String(120), nullable=False),
        sa.Column("normalized_alias", sa.String(128), nullable=False),
        sa.Column("alias", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "normalized_alias"),
    )


def downgrade() -> None:
    op.drop_table("identity_owner_group_aliases")
