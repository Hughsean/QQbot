"""Freeze the effective delivery decision for completed Agent runs.

Revision ID: 0026_effective_delivery
Revises: 0025_identity_mail_rules
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0026_effective_delivery"
down_revision: str | None = "0025_identity_mail_rules"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_runs",
        sa.Column("effective_delivery", sa.String(16), nullable=True),
    )
    op.create_check_constraint(
        "ck_agent_runs_effective_delivery",
        "agent_runs",
        "effective_delivery IS NULL OR effective_delivery IN ('HOLD', 'NOTIFY')",
    )
    op.execute(
        "UPDATE agent_runs SET effective_delivery = final_delivery "
        "WHERE status = 'COMPLETED' AND final_delivery IN ('HOLD', 'NOTIFY')"
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_agent_runs_effective_delivery", "agent_runs", type_="check"
    )
    op.drop_column("agent_runs", "effective_delivery")
