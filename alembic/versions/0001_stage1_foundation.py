"""Stage 1 operational and lifecycle foundations.

Revision ID: 0001_stage1
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_stage1"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    _create_operations_tables()
    _create_lifecycle_tables()


def downgrade() -> None:
    op.drop_table("data_lifecycle_purge_results")
    op.drop_table("data_lifecycle_tombstones")
    op.drop_index("ix_platform_jobs_due", table_name="platform_jobs")
    op.drop_table("platform_jobs")
    op.drop_index("ix_outbox_unpublished", table_name="platform_outbox_events")
    op.drop_table("platform_outbox_events")


def _create_operations_tables() -> None:
    op.create_table(
        "platform_outbox_events",
        sa.Column("event_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("event_type", sa.String(120), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("aggregate_ref", sa.String(200), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error_class", sa.String(80)),
    )
    op.create_index(
        "ix_outbox_unpublished", "platform_outbox_events", ["published_at", "occurred_at"]
    )
    op.create_table(
        "platform_jobs",
        sa.Column("job_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("kind", sa.String(100), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False, unique=True),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_owner", sa.String(120)),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("last_error_class", sa.String(80)),
        sa.Column("last_error_detail", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_platform_jobs_due", "platform_jobs", ["status", "available_at", "lease_until"]
    )


def _create_lifecycle_tables() -> None:
    op.create_table(
        "data_lifecycle_tombstones",
        sa.Column("tombstone_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("subject_ref", sa.String(240), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("purge_by", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "data_lifecycle_purge_results",
        sa.Column("result_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tombstone_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("data_lifecycle_tombstones.tombstone_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("module_name", sa.String(100), nullable=False),
        sa.Column("deleted_count", sa.Integer(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tombstone_id", "module_name", name="uq_purge_result_module"),
    )
