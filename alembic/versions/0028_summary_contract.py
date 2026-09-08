"""Add structured summary provenance and idempotency fields.

Revision ID: 0028_summary_contract
Revises: 0027_conversation_events
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0028_summary_contract"
down_revision: str | None = "0027_conversation_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_conversation_summaries",
        sa.Column("source_hash", sa.String(64), nullable=False, server_default=""),
    )
    op.add_column(
        "agent_conversation_summaries",
        sa.Column(
            "structured_json",
            postgresql.JSONB(),
            nullable=False,
            server_default="{}",
        ),
    )
    op.add_column(
        "agent_conversation_summaries",
        sa.Column("idempotency_key", sa.String(255), nullable=False, server_default=""),
    )
    op.create_unique_constraint(
        "uq_agent_conversation_summaries_idempotency",
        "agent_conversation_summaries",
        ["idempotency_key"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_agent_conversation_summaries_idempotency",
        "agent_conversation_summaries",
        type_="unique",
    )
    op.drop_column("agent_conversation_summaries", "idempotency_key")
    op.drop_column("agent_conversation_summaries", "structured_json")
    op.drop_column("agent_conversation_summaries", "source_hash")
