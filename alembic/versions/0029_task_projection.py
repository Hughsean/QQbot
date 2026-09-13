"""Add provider-neutral external task projection foundation.

Revision ID: 0029_task_projection
Revises: 0028_summary_contract
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0029_task_projection"
down_revision: str | None = "0028_summary_contract"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "task_projection_targets",
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(length=120), nullable=False),
        sa.Column("connection_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("provider_list_ref", sa.String(length=1024), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("target_id"),
        sa.UniqueConstraint(
            "provider", "connection_id", name="uq_task_projection_target_connection"
        ),
    )
    op.create_table(
        "task_projection_mappings",
        sa.Column("mapping_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(length=120), nullable=False),
        sa.Column("agenda_entry_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agenda_entry_version", sa.Integer(), nullable=False),
        sa.Column("connection_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("provider_list_ref", sa.String(length=1024), nullable=False),
        sa.Column("provider_task_ref", sa.String(length=1024), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("provider_revision", sa.String(length=1024), nullable=True),
        sa.Column("last_projected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_observed_completion", sa.Boolean(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("mapping_id"),
        sa.UniqueConstraint(
            "provider",
            "connection_id",
            "agenda_entry_id",
            name="uq_task_projection_mapping_agenda",
        ),
        sa.UniqueConstraint(
            "provider",
            "connection_id",
            "provider_task_ref",
            name="uq_task_projection_mapping_external",
        ),
    )
    op.create_index(
        "ix_task_projection_mapping_status",
        "task_projection_mappings",
        ["status"],
    )
    op.create_table(
        "task_projection_cursors",
        sa.Column("cursor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("connection_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("provider_list_ref", sa.String(length=1024), nullable=False),
        sa.Column("opaque_cursor", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("cursor_id"),
        sa.UniqueConstraint(
            "provider",
            "connection_id",
            "provider_list_ref",
            name="uq_task_projection_cursor_target",
        ),
    )


def downgrade() -> None:
    op.drop_table("task_projection_cursors")
    op.drop_index("ix_task_projection_mapping_status", table_name="task_projection_mappings")
    op.drop_table("task_projection_mappings")
    op.drop_table("task_projection_targets")
