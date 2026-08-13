"""Persist Inbox connection fences and source deletion identities.

Revision ID: 0012_inbox_deletion_fence
Revises: 0011_qq_mail_imap
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012_inbox_deletion_fence"
down_revision: str | None = "0011_qq_mail_imap"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "inbox_connection_states",
        sa.Column("connection_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("blocked", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("connection_id"),
    )
    op.create_table(
        "inbox_source_deletions",
        sa.Column("connection_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("external_id", sa.String(length=512), nullable=False),
        sa.Column("dedupe_key", sa.String(length=512), nullable=True),
        sa.Column(
            "deleted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("connection_id", "external_id"),
    )
    op.create_index(
        "ix_inbox_source_deletions_dedupe_key",
        "inbox_source_deletions",
        ["dedupe_key"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_inbox_source_deletions_dedupe_key", table_name="inbox_source_deletions")
    op.drop_table("inbox_source_deletions")
    op.drop_table("inbox_connection_states")
