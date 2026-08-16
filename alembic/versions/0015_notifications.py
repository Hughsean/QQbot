"""Add persistent notification intents and reminder state.

Revision ID: 0015_notifications
Revises: 0014_p1_foundation
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015_notifications"
down_revision: str | None = "0014_p1_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "notifications_intents",
        sa.Column("intent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(120), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("subject_key", sa.String(240), nullable=False),
        sa.Column("idempotency_key", sa.String(240), nullable=False),
        sa.Column("template_version", sa.String(80), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("state", sa.String(40), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("lease_owner", sa.String(120), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_delivery_id", sa.String(512), nullable=True),
        sa.Column("failure_class", sa.String(80), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("intent_id"),
        sa.UniqueConstraint("idempotency_key", name="uq_notifications_intent_idempotency"),
    )
    op.create_index(
        "ix_notifications_intent_due", "notifications_intents", ["state", "available_at"]
    )
    op.create_index(
        "ix_notifications_intent_subject_sent",
        "notifications_intents",
        ["subject_key", "sent_at"],
    )
    op.create_index(
        "uq_notifications_intent_blocking_subject",
        "notifications_intents",
        ["subject_key"],
        unique=True,
        postgresql_where=sa.text("state IN ('PENDING', 'LEASED', 'AMBIGUOUS', 'DEAD_LETTER')"),
    )
    _add_identity_preferences()
    op.add_column(
        "connections_external_connections",
        sa.Column("reauth_epoch", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "connections_external_connections",
        sa.Column("reauth_required_since", sa.DateTime(timezone=True), nullable=True),
    )
    op.alter_column("connections_external_connections", "reauth_epoch", server_default=None)


def downgrade() -> None:
    op.drop_column("connections_external_connections", "reauth_required_since")
    op.drop_column("connections_external_connections", "reauth_epoch")
    for name in (
        "quiet_end",
        "quiet_start",
        "quiet_hours_enabled",
        "reauth_notifications_enabled",
        "conflict_notifications_enabled",
        "digest_local_time",
        "digest_enabled",
    ):
        op.drop_column("identity_user_preferences", name)
    op.drop_index("uq_notifications_intent_blocking_subject", table_name="notifications_intents")
    op.drop_index("ix_notifications_intent_subject_sent", table_name="notifications_intents")
    op.drop_index("ix_notifications_intent_due", table_name="notifications_intents")
    op.drop_table("notifications_intents")


def _add_identity_preferences() -> None:
    table = "identity_user_preferences"
    columns = (
        sa.Column("digest_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("digest_local_time", sa.Time(), nullable=False, server_default="08:00:00"),
        sa.Column(
            "conflict_notifications_enabled", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column(
            "reauth_notifications_enabled", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column("quiet_hours_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("quiet_start", sa.Time(), nullable=False, server_default="22:00:00"),
        sa.Column("quiet_end", sa.Time(), nullable=False, server_default="07:00:00"),
    )
    for column in columns:
        op.add_column(table, column)
    for column in columns:
        op.alter_column(table, column.name, server_default=None)
