"""Add durable AgentRun execution claims and fencing epochs.

Revision ID: 0021_agent_run_execution_fencing
Revises: 0020_owner_group_aliases
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021_agent_run_execution_fencing"
down_revision: str | None = "0020_owner_group_aliases"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("agent_runs", sa.Column("execution_owner", sa.String(160), nullable=True))
    op.add_column(
        "agent_runs",
        sa.Column("execution_lease_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "agent_runs",
        sa.Column("execution_epoch", sa.Integer(), server_default="0", nullable=False),
    )
    op.create_index(
        "ix_agent_runs_execution_lease",
        "agent_runs",
        ["status", "execution_lease_until"],
    )


def downgrade() -> None:
    op.drop_index("ix_agent_runs_execution_lease", table_name="agent_runs")
    op.drop_column("agent_runs", "execution_epoch")
    op.drop_column("agent_runs", "execution_lease_until")
    op.drop_column("agent_runs", "execution_owner")
