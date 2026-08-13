"""Stage 8 idempotent deletion request storage.

Revision ID: 0010_tombstone_idempotency
Revises: 0009_derived_deletion
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_tombstone_idempotency"
down_revision: str | None = "0009_derived_deletion"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "data_lifecycle_tombstones",
        "subject_ref",
        existing_type=sa.String(240),
        type_=sa.String(512),
        existing_nullable=False,
    )
    op.execute(
        """
        DELETE FROM data_lifecycle_tombstones AS duplicate
        USING data_lifecycle_tombstones AS keeper
        WHERE duplicate.subject_ref = keeper.subject_ref
          AND (duplicate.requested_at, duplicate.tombstone_id)
              > (keeper.requested_at, keeper.tombstone_id)
        """
    )
    op.create_unique_constraint(
        "uq_lifecycle_tombstone_subject",
        "data_lifecycle_tombstones",
        ["subject_ref"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_lifecycle_tombstone_subject",
        "data_lifecycle_tombstones",
        type_="unique",
    )
    op.alter_column(
        "data_lifecycle_tombstones",
        "subject_ref",
        existing_type=sa.String(512),
        type_=sa.String(240),
        existing_nullable=False,
    )
