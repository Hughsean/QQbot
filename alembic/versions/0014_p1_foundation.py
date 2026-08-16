"""Add source asset and multi-connection foundations.

Revision ID: 0014_p1_foundation
Revises: 0013_schema_alignment
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014_p1_foundation"
down_revision: str | None = "0013_schema_alignment"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    _upgrade_connections()
    _create_source_assets()
    _create_normalized_assets()
    _create_calendar_change_candidates()


def downgrade() -> None:
    op.execute(sa.text("DROP TABLE IF EXISTS understanding_calendar_change_candidates"))
    op.drop_table("normalization_assets")
    op.drop_table("inbox_source_assets")
    op.drop_index("uq_connections_default_provider", table_name="connections_external_connections")
    op.drop_index("uq_connections_active_identity", table_name="connections_external_connections")
    op.drop_index("ix_connections_user_provider", table_name="connections_external_connections")
    op.create_unique_constraint(
        "uq_connections_user_provider",
        "connections_external_connections",
        ["user_id", "provider"],
    )
    op.drop_column("connections_external_connections", "sync_enabled")
    op.drop_column("connections_external_connections", "is_default")
    op.drop_column("connections_external_connections", "display_label")
    op.drop_column("connections_external_connections", "account_fingerprint")


def _upgrade_connections() -> None:
    op.add_column(
        "connections_external_connections",
        sa.Column("account_fingerprint", sa.String(length=80), nullable=True),
    )
    op.add_column(
        "connections_external_connections",
        sa.Column("display_label", sa.String(length=120), nullable=False, server_default="Mailbox"),
    )
    op.add_column(
        "connections_external_connections",
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "connections_external_connections",
        sa.Column("sync_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.execute(
        sa.text(
            "UPDATE connections_external_connections "
            "SET account_fingerprint = 'legacy:' || connection_id::text, "
            "display_label = COALESCE(NULLIF(account_mask, ''), provider)"
        )
    )
    op.drop_constraint(
        "uq_connections_user_provider", "connections_external_connections", type_="unique"
    )
    op.create_index(
        "ix_connections_user_provider",
        "connections_external_connections",
        ["user_id", "provider"],
    )
    op.create_index(
        "uq_connections_active_identity",
        "connections_external_connections",
        ["user_id", "provider", "account_fingerprint"],
        unique=True,
        postgresql_where=sa.text("account_fingerprint IS NOT NULL AND status <> 'DISCONNECTED'"),
    )
    op.create_index(
        "uq_connections_default_provider",
        "connections_external_connections",
        ["user_id", "provider"],
        unique=True,
        postgresql_where=sa.text(
            "is_default IS TRUE AND status IN ('ACTIVE', 'DEGRADED', 'REAUTH_REQUIRED')"
        ),
    )
    op.alter_column("connections_external_connections", "display_label", server_default=None)
    op.alter_column("connections_external_connections", "is_default", server_default=None)
    op.alter_column("connections_external_connections", "sync_enabled", server_default=None)


def _create_source_assets() -> None:
    op.create_table(
        "inbox_source_assets",
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("inbox_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider_asset_id", sa.String(length=512), nullable=False),
        sa.Column("provider_locator", sa.String(length=512), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("filename", sa.String(length=512), nullable=True),
        sa.Column("declared_content_type", sa.String(length=255), nullable=False),
        sa.Column("detected_content_type", sa.String(length=255), nullable=True),
        sa.Column("declared_size", sa.Integer(), nullable=True),
        sa.Column("transfer_encoding", sa.String(length=40), nullable=True),
        sa.Column("actual_size", sa.Integer(), nullable=True),
        sa.Column("content_sha256", sa.String(length=64), nullable=True),
        sa.Column("storage_key", sa.String(length=80), nullable=True),
        sa.Column("trust_level", sa.String(length=10), nullable=False),
        sa.Column("fetch_status", sa.String(length=40), nullable=False),
        sa.Column("parse_status", sa.String(length=40), nullable=False),
        sa.Column("parser_version", sa.String(length=120), nullable=True),
        sa.Column("failure_class", sa.String(length=80), nullable=True),
        sa.Column("purge_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("parsed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint("trust_level = 'T2'", name="ck_inbox_assets_t2"),
        sa.CheckConstraint(
            "declared_size IS NULL OR declared_size >= 0", name="ck_asset_declared_size"
        ),
        sa.CheckConstraint("actual_size IS NULL OR actual_size >= 0", name="ck_asset_actual_size"),
        sa.ForeignKeyConstraint(
            ["inbox_item_id"], ["inbox_items.inbox_item_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("asset_id"),
        sa.UniqueConstraint(
            "inbox_item_id", "provider_asset_id", name="uq_inbox_assets_parent_provider"
        ),
    )
    op.create_index("ix_inbox_assets_parent", "inbox_source_assets", ["inbox_item_id"])
    op.create_index(
        "ix_inbox_assets_fetch_parse",
        "inbox_source_assets",
        ["fetch_status", "parse_status", "created_at"],
    )
    op.create_index("ix_inbox_assets_purge", "inbox_source_assets", ["purge_at", "deleted_at"])


def _create_normalized_assets() -> None:
    op.create_table(
        "normalization_assets",
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("inbox_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("parser_version", sa.String(length=120), nullable=False),
        sa.Column("source_ref", sa.String(length=512), nullable=True),
        sa.Column("calendar_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint("asset_id"),
    )
    op.create_index(
        "ix_normalization_assets_inbox_item_id",
        "normalization_assets",
        ["inbox_item_id"],
    )
    op.create_index("ix_normalization_assets_source_ref", "normalization_assets", ["source_ref"])


def _create_calendar_change_candidates() -> None:
    table = "understanding_calendar_change_candidates"
    op.create_table(
        table,
        sa.Column("candidate_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("inbox_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("external_event_key", sa.String(length=64), nullable=False),
        sa.Column("version_key", sa.String(length=64), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("change_kind", sa.String(length=20), nullable=False),
        sa.Column("state", sa.String(length=40), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("timezone", sa.String(length=80), nullable=False),
        sa.Column("location", sa.Text(), nullable=True),
        sa.Column("participants", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("recurrence_rule", sa.Text(), nullable=True),
        sa.Column("agenda_entry_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("parent_source_ref", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("candidate_id"),
        sa.UniqueConstraint("version_key", name="uq_understanding_calendar_version"),
    )
    op.create_index("ix_understanding_calendar_change_candidates_asset_id", table, ["asset_id"])
    op.create_index(
        "ix_understanding_calendar_change_candidates_inbox_item_id",
        table,
        ["inbox_item_id"],
    )
    op.create_index(
        "ix_understanding_calendar_change_candidates_parent_source_ref",
        table,
        ["parent_source_ref"],
    )
    op.create_index(
        "ix_understanding_calendar_event_sequence",
        table,
        ["external_event_key", "sequence"],
    )
