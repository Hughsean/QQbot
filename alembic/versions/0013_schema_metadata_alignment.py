"""Align operational constraint naming with declared metadata.

Revision ID: 0013_schema_alignment
Revises: 0012_inbox_deletion_fence
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_schema_alignment"
down_revision: str | None = "0012_inbox_deletion_fence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "ALTER TABLE platform_jobs RENAME CONSTRAINT "
            "platform_jobs_idempotency_key_key TO uq_platform_jobs_idempotency"
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "ALTER TABLE platform_jobs RENAME CONSTRAINT "
            "uq_platform_jobs_idempotency TO platform_jobs_idempotency_key_key"
        )
    )
