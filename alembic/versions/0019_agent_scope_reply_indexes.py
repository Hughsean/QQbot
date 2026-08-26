"""Index completed Agent replies by logical context scope."""

from collections.abc import Sequence

from alembic import op

revision: str = "0019_agent_scope_reply_indexes"
down_revision: str | None = "0018_agent_run_delivery"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_agent_runs_conversation_reply_time",
        "agent_runs",
        ["conversation_id", "updated_at"],
    )
    op.create_index(
        "ix_agent_runs_event_reply_time",
        "agent_runs",
        ["event_case_id", "updated_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_agent_runs_event_reply_time", table_name="agent_runs")
    op.drop_index("ix_agent_runs_conversation_reply_time", table_name="agent_runs")
