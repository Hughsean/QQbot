"""QQ Mail IMAP dedupe, attachment metadata and opaque cursor.

Revision ID: 0011_qq_mail_imap
Revises: 0010_tombstone_idempotency
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011_qq_mail_imap"
down_revision: str | None = "0010_tombstone_idempotency"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("inbox_items", sa.Column("dedupe_key", sa.String(512), nullable=True))
    op.create_unique_constraint(
        "uq_inbox_connection_dedupe", "inbox_items", ["connection_id", "dedupe_key"]
    )
    op.add_column(
        "inbox_raw_contents",
        sa.Column(
            "attachment_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.alter_column(
        "inbox_sync_cursors",
        "cursor_url",
        new_column_name="cursor_value",
        existing_type=sa.Text(),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "inbox_sync_cursors",
        "cursor_value",
        new_column_name="cursor_url",
        existing_type=sa.Text(),
        existing_nullable=False,
    )
    op.drop_column("inbox_raw_contents", "attachment_metadata")
    op.drop_constraint("uq_inbox_connection_dedupe", "inbox_items", type_="unique")
    op.drop_column("inbox_items", "dedupe_key")
