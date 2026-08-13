"""Stage 8 derived Understanding, Scheduling and Workflow deletion.

Revision ID: 0009_derived_deletion
Revises: 0008_privacy_hardening
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_derived_deletion"
down_revision: str | None = "0008_privacy_hardening"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "understanding_candidates", sa.Column("source_ref", sa.String(512), nullable=True)
    )
    op.execute(
        """
        UPDATE understanding_candidates AS candidate
        SET source_ref = COALESCE(normalized.source_ref, candidate.source_refs[1])
        FROM normalization_contents AS normalized
        WHERE normalized.inbox_item_id = candidate.inbox_item_id
          AND candidate.source_ref IS NULL
        """
    )
    op.execute(
        "UPDATE understanding_candidates SET source_ref = source_refs[1] WHERE source_ref IS NULL"
    )
    op.alter_column("understanding_candidates", "source_ref", nullable=False)
    op.create_index(
        "ix_understanding_candidates_source_ref",
        "understanding_candidates",
        ["source_ref"],
    )
    op.add_column("scheduling_proposals", sa.Column("source_ref", sa.String(512), nullable=True))
    op.execute(
        """
        UPDATE scheduling_proposals AS proposal
        SET source_ref = COALESCE(candidate.source_ref, proposal.source_refs[1])
        FROM understanding_candidates AS candidate
        WHERE candidate.candidate_id = proposal.candidate_id
          AND proposal.source_ref IS NULL
        """
    )
    op.execute(
        "UPDATE scheduling_proposals SET source_ref = source_refs[1] WHERE source_ref IS NULL"
    )
    op.alter_column("scheduling_proposals", "source_ref", nullable=False)
    op.create_index("ix_scheduling_proposals_source_ref", "scheduling_proposals", ["source_ref"])
    op.add_column(
        "workflow_understanding_checkpoints",
        sa.Column("source_ref", sa.String(512), nullable=True),
    )
    op.execute(
        """
        UPDATE workflow_understanding_checkpoints AS checkpoint
        SET source_ref = normalized.source_ref
        FROM normalization_contents AS normalized
        WHERE normalized.inbox_item_id = checkpoint.inbox_item_id
        """
    )
    op.create_index(
        "ix_workflow_understanding_checkpoints_source_ref",
        "workflow_understanding_checkpoints",
        ["source_ref"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_workflow_understanding_checkpoints_source_ref",
        table_name="workflow_understanding_checkpoints",
    )
    op.drop_column("workflow_understanding_checkpoints", "source_ref")
    op.drop_index("ix_scheduling_proposals_source_ref", table_name="scheduling_proposals")
    op.drop_column("scheduling_proposals", "source_ref")
    op.drop_index("ix_understanding_candidates_source_ref", table_name="understanding_candidates")
    op.drop_column("understanding_candidates", "source_ref")
