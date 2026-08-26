"""Persist the Agent's outbound delivery decision."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_agent_run_delivery"
down_revision: str | None = "0017_context_scopes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("agent_runs", sa.Column("final_delivery", sa.String(16), nullable=True))
    op.execute(
        "UPDATE agent_runs SET final_delivery = 'HOLD' "
        "WHERE status = 'COMPLETED' AND final_content IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_column("agent_runs", "final_delivery")
