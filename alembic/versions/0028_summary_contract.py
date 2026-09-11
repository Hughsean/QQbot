"""Add structured summary provenance and idempotency fields.

Revision ID: 0028_summary_contract
Revises: 0027_conversation_events
"""

from collections.abc import Sequence
from hashlib import sha256

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Connection, RowMapping

revision: str = "0028_summary_contract"
down_revision: str | None = "0027_conversation_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_conversation_summaries",
        sa.Column("source_hash", sa.String(64), nullable=True),
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
        sa.Column("idempotency_key", sa.String(255), nullable=True),
    )
    _backfill_existing_summaries()
    op.alter_column("agent_conversation_summaries", "source_hash", nullable=False)
    op.alter_column("agent_conversation_summaries", "idempotency_key", nullable=False)
    op.create_unique_constraint(
        "uq_agent_conversation_summaries_idempotency",
        "agent_conversation_summaries",
        ["idempotency_key"],
    )


def _backfill_existing_summaries() -> None:
    connection = op.get_bind()
    summaries = connection.execute(
        sa.text(
            "SELECT summary_id, user_id, scope_type, scope_id, from_sequence, "
            "to_sequence, content_hash FROM agent_conversation_summaries"
        )
    ).mappings()
    for summary in summaries:
        source_hash = _legacy_source_hash(connection, summary)
        connection.execute(
            sa.text(
                "UPDATE agent_conversation_summaries "
                "SET source_hash = :source_hash, idempotency_key = :idempotency_key "
                "WHERE summary_id = :summary_id"
            ),
            {
                "summary_id": summary["summary_id"],
                "source_hash": source_hash,
                "idempotency_key": f"legacy-summary:{summary['summary_id']}",
            },
        )


def _legacy_source_hash(connection: Connection, summary: RowMapping) -> str:
    events = connection.execute(
        sa.text(
            "SELECT user_id, scope_type, scope_id, sequence, event_id, content_hash "
            "FROM agent_conversation_events WHERE user_id = :user_id "
            "AND scope_type = :scope_type AND scope_id = :scope_id "
            "AND sequence BETWEEN :from_sequence AND :to_sequence ORDER BY sequence"
        ),
        dict(summary),
    ).mappings()
    parts = [
        f"{row['user_id']}:{row['scope_type']}:{row['scope_id']}:{row['sequence']}:"
        f"{row['event_id']}:{row['content_hash']}"
        for row in events
    ]
    if parts:
        return sha256("|".join(parts).encode("utf-8")).hexdigest()
    fallback = f"legacy-summary:{summary['summary_id']}:{summary['content_hash']}"
    return sha256(fallback.encode("utf-8")).hexdigest()


def downgrade() -> None:
    op.drop_constraint(
        "uq_agent_conversation_summaries_idempotency",
        "agent_conversation_summaries",
        type_="unique",
    )
    op.drop_column("agent_conversation_summaries", "idempotency_key")
    op.drop_column("agent_conversation_summaries", "structured_json")
    op.drop_column("agent_conversation_summaries", "source_hash")
