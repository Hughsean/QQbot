"""Stage 2 encrypted credentials and Microsoft connection lifecycle.

Revision ID: 0002_connections
Revises: 0001_stage1
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_connections"
down_revision: str | None = "0001_stage1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "credentials_vault_records",
        sa.Column("credential_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("key_version", sa.Integer(), nullable=False),
        sa.Column("nonce", sa.LargeBinary(), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "connections_external_connections",
        sa.Column("connection_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.String(120), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("provider_account_id", sa.String(200)),
        sa.Column("account_mask", sa.String(240)),
        sa.Column("capabilities", postgresql.JSONB(), nullable=False),
        sa.Column("credential_ref", postgresql.UUID(as_uuid=True)),
        sa.Column("last_synced_at", sa.DateTime(timezone=True)),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.UniqueConstraint("user_id", "provider", name="uq_connections_user_provider"),
    )
    op.create_table(
        "connections_oauth_transactions",
        sa.Column("transaction_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("connection_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(120), nullable=False),
        sa.Column("state_hash", sa.LargeBinary(32), nullable=False, unique=True),
        sa.Column("browser_session_hash", sa.LargeBinary(32), nullable=False),
        sa.Column("flow_credential_ref", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_connections_oauth_claim",
        "connections_oauth_transactions",
        ["state_hash", "expires_at", "consumed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_connections_oauth_claim", table_name="connections_oauth_transactions")
    op.drop_table("connections_oauth_transactions")
    op.drop_table("connections_external_connections")
    op.drop_table("credentials_vault_records")
