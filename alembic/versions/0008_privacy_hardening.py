"""Stage 8 append-only Audit and deletion source references.

Revision ID: 0008_privacy_hardening
Revises: 0007_knowledge_retrieval
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_privacy_hardening"
down_revision: str | None = "0007_knowledge_retrieval"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("normalization_contents", sa.Column("source_ref", sa.String(512), nullable=True))
    op.create_index(
        "ix_normalization_contents_source_ref",
        "normalization_contents",
        ["source_ref"],
    )
    op.execute(
        """
        UPDATE normalization_contents AS normalized
        SET source_ref = CASE inbox.source_type
            WHEN 'MICROSOFT_MAIL' THEN 'mail:'
            WHEN 'QQ_FORWARD' THEN 'qq-forward:'
            WHEN 'OWNER_NOTE' THEN 'owner-note:'
            ELSE 'qq:'
        END || inbox.connection_id::text || ':' || inbox.external_id
        FROM inbox_items AS inbox
        WHERE inbox.inbox_item_id = normalized.inbox_item_id
          AND normalized.source_ref IS NULL
        """
    )
    op.create_table(
        "audit_events",
        sa.Column("audit_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("actor_ref", sa.String(120), nullable=False),
        sa.Column("subject_ref", sa.String(512), nullable=False),
        sa.Column("outcome", sa.String(40), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=False),
    )
    op.create_index("ix_audit_event_time", "audit_events", ["event_type", "occurred_at"])


def downgrade() -> None:
    op.drop_index("ix_audit_event_time", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index("ix_normalization_contents_source_ref", table_name="normalization_contents")
    op.drop_column("normalization_contents", "source_ref")
