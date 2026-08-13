"""Stage 3 idempotent mail Inbox and deterministic normalization.

Revision ID: 0003_mail_inbox
Revises: 0002_connections
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_mail_inbox"
down_revision: str | None = "0002_connections"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "inbox_raw_contents",
        sa.Column("raw_content_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("body_text", sa.Text(), nullable=False),
        sa.Column("body_html", sa.Text()),
        sa.Column("mime_type", sa.String(80), nullable=False),
        sa.Column("recipients", postgresql.JSONB(), nullable=False),
        sa.Column("internet_message_id", sa.String(998)),
        sa.Column("change_key", sa.String(512)),
        sa.Column("has_attachments", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "inbox_items",
        sa.Column("inbox_item_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("connection_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(120), nullable=False),
        sa.Column("source_type", sa.String(40), nullable=False),
        sa.Column("ingress_type", sa.String(40), nullable=False),
        sa.Column("trust_level", sa.String(10), nullable=False),
        sa.Column("external_id", sa.String(512), nullable=False),
        sa.Column("thread_id", sa.String(512)),
        sa.Column("sender_id", sa.String(320), nullable=False),
        sa.Column("sender_display", sa.String(320)),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_content_ref", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("failure_class", sa.String(80)),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("connection_id", "external_id", name="uq_inbox_connection_external"),
    )
    op.create_index("ix_inbox_status_received", "inbox_items", ["status", "received_at"])
    op.create_table(
        "inbox_sync_cursors",
        sa.Column("connection_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("cursor_url", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "normalization_contents",
        sa.Column("inbox_item_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("normalizer_version", sa.String(80), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("normalization_contents")
    op.drop_table("inbox_sync_cursors")
    op.drop_index("ix_inbox_status_received", table_name="inbox_items")
    op.drop_table("inbox_items")
    op.drop_table("inbox_raw_contents")
