"""Initial schema baseline.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-09-14

Squash of the historical chain 0001_stage1..0031_agent_turn_batches; the rendered
upgrade body reproduces exactly the schema those migrations produced (verified by
the schema-metadata alignment gate). Databases created before the squash are
aligned by ops/baseline-cutover-to-initial-schema.sql instead of replaying history.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import VECTOR
from sqlalchemy import Integer, Text
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_table(
        "actions_requests",
        sa.Column("action_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.String(length=120), nullable=False),
        sa.Column("action_type", sa.String(length=30), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("proposal_id", sa.UUID(), nullable=True),
        sa.Column("proposal_version", sa.Integer(), nullable=True),
        sa.Column("agenda_entry_id", sa.UUID(), nullable=True),
        sa.Column("agenda_entry_version", sa.Integer(), nullable=True),
        sa.Column("reminder_id", sa.UUID(), nullable=True),
        sa.Column("failure_class", sa.String(length=120), nullable=True),
        sa.Column("operation_payload", postgresql.JSONB(astext_type=Text()), nullable=True),
        sa.PrimaryKeyConstraint("action_id"),
        sa.UniqueConstraint("idempotency_key", name="uq_actions_idempotency"),
    )
    op.create_table(
        "agenda_entries",
        sa.Column("agenda_entry_id", sa.UUID(), nullable=False),
        sa.Column("action_id", sa.UUID(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("timezone", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("source_refs", postgresql.ARRAY(Text()), nullable=False),
        sa.Column("proposal_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("last_operation_key", sa.String(length=200), nullable=False),
        sa.PrimaryKeyConstraint("agenda_entry_id"),
        sa.UniqueConstraint("idempotency_key", name="uq_agenda_idempotency"),
    )
    op.create_index(
        "ix_agenda_active_range", "agenda_entries", ["status", "starts_at", "ends_at"], unique=False
    )
    op.create_table(
        "agent_context_items",
        sa.Column("scope_type", sa.String(length=20), nullable=False),
        sa.Column("scope_id", sa.UUID(), nullable=False),
        sa.Column("inbox_item_id", sa.UUID(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("scope_type", "scope_id", "inbox_item_id"),
    )
    op.create_index(
        "ix_agent_context_items_scope_time",
        "agent_context_items",
        ["scope_type", "scope_id", "occurred_at"],
        unique=False,
    )
    op.create_table(
        "agent_conversation_events",
        sa.Column("event_id", sa.UUID(), nullable=False),
        sa.Column("scope_type", sa.String(length=20), nullable=False),
        sa.Column("scope_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.String(length=120), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_ref", sa.String(length=160), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("delivery_status", sa.String(length=16), nullable=True),
        sa.Column("run_id", sa.UUID(), nullable=True),
        sa.Column("inbox_item_id", sa.UUID(), nullable=True),
        sa.Column("notification_intent_id", sa.UUID(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=Text()), nullable=False),
        sa.CheckConstraint(
            "delivery_status IS NULL OR delivery_status IN ('DELIVERED', 'FAILED')",
            name="ck_agent_conversation_events_delivery",
        ),
        sa.CheckConstraint(
            "event_type IN ('USER_MESSAGE', 'AGENT_REPLY', 'TOOL_CALL', 'TOOL_RESULT', "
            "'MAIL_NOTIFICATION', 'MAIL_DIGEST', 'DAILY_DIGEST', 'SYSTEM_RESULT')",
            name="ck_agent_conversation_events_type",
        ),
        sa.CheckConstraint(
            "role IN ('user', 'agent', 'tool', 'system')", name="ck_agent_conversation_events_role"
        ),
        sa.CheckConstraint(
            "scope_type IN ('conversation', 'owner_timeline')",
            name="ck_agent_conversation_events_scope",
        ),
        sa.CheckConstraint("sequence >= 1", name="ck_agent_conversation_events_sequence"),
        sa.PrimaryKeyConstraint("event_id"),
        sa.UniqueConstraint("idempotency_key", name="uq_agent_conversation_events_idempotency"),
        sa.UniqueConstraint(
            "scope_type", "scope_id", "sequence", name="uq_agent_conversation_events_scope_sequence"
        ),
        sa.UniqueConstraint(
            "user_id", "sequence", name="uq_agent_conversation_events_user_sequence"
        ),
    )
    op.create_index(
        "ix_agent_conversation_events_scope_time",
        "agent_conversation_events",
        ["scope_type", "scope_id", "occurred_at"],
        unique=False,
    )
    op.create_table(
        "agent_conversation_sequence_counters",
        sa.Column("user_id", sa.String(length=120), nullable=False),
        sa.Column("last_sequence", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_table(
        "agent_conversation_summaries",
        sa.Column("summary_id", sa.UUID(), nullable=False),
        sa.Column("scope_type", sa.String(length=20), nullable=False),
        sa.Column("scope_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.String(length=120), nullable=False),
        sa.Column("summary_kind", sa.String(length=40), nullable=False),
        sa.Column("from_sequence", sa.Integer(), nullable=False),
        sa.Column("to_sequence", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "structured_json",
            postgresql.JSONB(astext_type=Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "scope_type IN ('conversation', 'owner_timeline')",
            name="ck_agent_conversation_summaries_scope",
        ),
        sa.CheckConstraint(
            "from_sequence >= 1 AND to_sequence >= from_sequence",
            name="ck_agent_conversation_summaries_range",
        ),
        sa.PrimaryKeyConstraint("summary_id"),
        sa.UniqueConstraint("idempotency_key", name="uq_agent_conversation_summaries_idempotency"),
        sa.UniqueConstraint(
            "scope_type",
            "scope_id",
            "from_sequence",
            "to_sequence",
            name="uq_agent_conversation_summaries_range",
        ),
    )
    op.create_index(
        "ix_agent_conversation_summaries_scope_to",
        "agent_conversation_summaries",
        ["scope_type", "scope_id", "to_sequence"],
        unique=False,
    )
    op.create_table(
        "agent_conversations",
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.String(length=120), nullable=False),
        sa.Column("channel", sa.String(length=40), nullable=False),
        sa.Column("conversation_key", sa.String(length=512), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("conversation_id"),
        sa.UniqueConstraint(
            "user_id", "channel", "conversation_key", name="uq_agent_conversation_scope"
        ),
    )
    op.create_table(
        "agent_event_cases",
        sa.Column("event_case_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.String(length=120), nullable=False),
        sa.Column("event_key", sa.String(length=512), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("event_case_id"),
        sa.UniqueConstraint("user_id", "event_key", name="uq_agent_event_scope"),
    )
    op.create_table(
        "agent_run_events",
        sa.Column("event_id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("step", sa.Integer(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_class", sa.String(length=120), nullable=True),
        sa.Column("tool_name", sa.String(length=120), nullable=True),
        sa.Column("call_id", sa.String(length=160), nullable=True),
        sa.Column("invocation_id", sa.UUID(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=Text()), nullable=False),
        sa.PrimaryKeyConstraint("event_id"),
        sa.UniqueConstraint("run_id", "idempotency_key", name="uq_agent_run_events_idempotency"),
        sa.UniqueConstraint("run_id", "sequence", name="uq_agent_run_events_sequence"),
    )
    op.create_index(
        "ix_agent_run_events_run_scope", "agent_run_events", ["run_id", "sequence"], unique=False
    )
    op.create_index(
        "ix_agent_run_events_run_time", "agent_run_events", ["run_id", "occurred_at"], unique=False
    )
    op.create_table(
        "agent_runs",
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("inbox_item_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.String(length=120), nullable=False),
        sa.Column("source_type", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("step", sa.Integer(), nullable=False),
        sa.Column("observations", postgresql.JSONB(astext_type=Text()), nullable=False),
        sa.Column("final_content", sa.Text(), nullable=True),
        sa.Column("final_delivery", sa.String(length=16), nullable=True),
        sa.Column("effective_delivery", sa.String(length=16), nullable=True),
        sa.Column("failure_class", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=True),
        sa.Column("event_case_id", sa.UUID(), nullable=True),
        sa.Column("execution_owner", sa.String(length=160), nullable=True),
        sa.Column("execution_lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("execution_epoch", sa.Integer(), server_default="0", nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("context_revision", sa.Integer(), nullable=True),
        sa.Column("context_max_sequence", sa.Integer(), nullable=True),
        sa.Column("context_hash", sa.String(length=64), nullable=True),
        sa.Column("source_refs", postgresql.JSONB(astext_type=Text()), nullable=False),
        sa.CheckConstraint(
            "effective_delivery IS NULL OR effective_delivery IN ('HOLD', 'NOTIFY')",
            name="ck_agent_runs_effective_delivery",
        ),
        sa.PrimaryKeyConstraint("run_id"),
        sa.UniqueConstraint("inbox_item_id", name="uq_agent_runs_inbox_item"),
    )
    op.create_index("ix_agent_runs_completed", "agent_runs", ["completed_at"], unique=False)
    op.create_index(
        "ix_agent_runs_conversation_reply_time",
        "agent_runs",
        ["conversation_id", "updated_at"],
        unique=False,
    )
    op.create_index(
        "ix_agent_runs_event_reply_time",
        "agent_runs",
        ["event_case_id", "updated_at"],
        unique=False,
    )
    op.create_index(
        "ix_agent_runs_execution_lease",
        "agent_runs",
        ["status", "execution_lease_until"],
        unique=False,
    )
    op.create_index(
        "ix_agent_runs_status_updated", "agent_runs", ["status", "updated_at"], unique=False
    )
    op.create_table(
        "agent_tool_calls",
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("call_id", sa.String(length=160), nullable=False),
        sa.Column("tool_name", sa.String(length=120), nullable=False),
        sa.Column("arguments_hash", sa.String(length=128), nullable=False),
        sa.Column("observation", postgresql.JSONB(astext_type=Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("run_id", "call_id"),
    )
    op.create_table(
        "agent_turn_batches",
        sa.Column("turn_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.String(length=120), nullable=False),
        sa.Column("conversation_key_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("message_count", sa.Integer(), nullable=False),
        sa.Column("content_chars", sa.Integer(), nullable=False),
        sa.Column("ready_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("hard_deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_owner", sa.String(length=160), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_class", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('OPEN', 'LEASED', 'COMPLETED', 'FAILED')",
            name="ck_agent_turn_batches_status",
        ),
        sa.CheckConstraint(
            "generation >= 1 AND message_count >= 1 AND content_chars >= 0",
            name="ck_agent_turn_batches_counts",
        ),
        sa.PrimaryKeyConstraint("turn_id"),
    )
    op.create_index(
        "ix_agent_turn_batches_conversation_status",
        "agent_turn_batches",
        ["conversation_key_hash", "status", "created_at"],
        unique=False,
    )
    op.create_table(
        "ai_gateway_invocations",
        sa.Column("invocation_id", sa.UUID(), nullable=False),
        sa.Column("use_case", sa.String(length=80), nullable=False),
        sa.Column("prompt_version", sa.String(length=80), nullable=False),
        sa.Column("route", sa.String(length=20), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("failure_class", sa.String(length=80), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("invocation_id"),
    )
    op.create_table(
        "audit_events",
        sa.Column("audit_id", sa.UUID(), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("actor_ref", sa.String(length=120), nullable=False),
        sa.Column("subject_ref", sa.String(length=512), nullable=False),
        sa.Column("outcome", sa.String(length=40), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=Text()), nullable=False),
        sa.PrimaryKeyConstraint("audit_id"),
    )
    op.create_index(
        "ix_audit_event_time", "audit_events", ["event_type", "occurred_at"], unique=False
    )
    op.create_table(
        "connections_external_connections",
        sa.Column("connection_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.String(length=120), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("provider_account_id", sa.String(length=200), nullable=True),
        sa.Column("account_mask", sa.String(length=240), nullable=True),
        sa.Column("account_fingerprint", sa.String(length=80), nullable=True),
        sa.Column("display_label", sa.String(length=120), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("sync_enabled", sa.Boolean(), nullable=False),
        sa.Column("capabilities", postgresql.JSONB(astext_type=Text()), nullable=False),
        sa.Column("credential_ref", sa.UUID(), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reauth_epoch", sa.Integer(), nullable=False),
        sa.Column("reauth_required_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("connection_id"),
    )
    op.create_index(
        "ix_connections_user_provider",
        "connections_external_connections",
        ["user_id", "provider"],
        unique=False,
    )
    op.create_index(
        "uq_connections_active_identity",
        "connections_external_connections",
        ["user_id", "provider", "account_fingerprint"],
        unique=True,
        postgresql_where=sa.text("account_fingerprint IS NOT NULL AND status != 'DISCONNECTED'"),
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
    op.create_table(
        "connections_oauth_transactions",
        sa.Column("transaction_id", sa.UUID(), nullable=False),
        sa.Column("connection_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.String(length=120), nullable=False),
        sa.Column("state_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("browser_session_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("flow_credential_ref", sa.UUID(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("transaction_id"),
        sa.UniqueConstraint("state_hash"),
    )
    op.create_index(
        "ix_connections_oauth_claim",
        "connections_oauth_transactions",
        ["state_hash", "expires_at", "consumed_at"],
        unique=False,
    )
    op.create_table(
        "credentials_vault_records",
        sa.Column("credential_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("key_version", sa.Integer(), nullable=False),
        sa.Column("nonce", sa.LargeBinary(), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("credential_id"),
    )
    op.create_table(
        "data_lifecycle_tombstones",
        sa.Column("tombstone_id", sa.UUID(), nullable=False),
        sa.Column("subject_ref", sa.String(length=512), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("purge_by", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("tombstone_id"),
        sa.UniqueConstraint("subject_ref", name="uq_lifecycle_tombstone_subject"),
    )
    op.create_table(
        "identity_mail_rules",
        sa.Column("rule_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.String(length=120), nullable=False),
        sa.Column("match_field", sa.String(length=20), nullable=False),
        sa.Column("pattern", sa.String(length=240), nullable=False),
        sa.Column("normalized_pattern", sa.String(length=240), nullable=False),
        sa.Column("action", sa.String(length=10), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("action IN ('NOTIFY', 'HOLD')", name="ck_mail_rules_action"),
        sa.CheckConstraint(
            "match_field IN ('SENDER', 'SUBJECT')", name="ck_mail_rules_match_field"
        ),
        sa.PrimaryKeyConstraint("rule_id"),
        sa.UniqueConstraint(
            "user_id",
            "match_field",
            "normalized_pattern",
            name="identity_mail_rules_user_id_match_field_normalized_pattern_key",
        ),
    )
    op.create_index(
        "ix_identity_mail_rules_user",
        "identity_mail_rules",
        ["user_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "identity_owner_group_aliases",
        sa.Column("user_id", sa.String(length=120), nullable=False),
        sa.Column("normalized_alias", sa.String(length=128), nullable=False),
        sa.Column("alias", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "normalized_alias"),
    )
    op.create_table(
        "identity_user_preferences",
        sa.Column("user_id", sa.String(length=120), nullable=False),
        sa.Column("timezone", sa.String(length=80), nullable=False),
        sa.Column("work_start", sa.Time(), nullable=False),
        sa.Column("work_end", sa.Time(), nullable=False),
        sa.Column("lunch_start", sa.Time(), nullable=False),
        sa.Column("lunch_end", sa.Time(), nullable=False),
        sa.Column("working_weekdays", postgresql.ARRAY(Integer()), nullable=False),
        sa.Column("default_event_minutes", sa.Integer(), nullable=False),
        sa.Column("default_task_minutes", sa.Integer(), nullable=False),
        sa.Column("digest_enabled", sa.Boolean(), nullable=False),
        sa.Column("digest_local_time", sa.Time(), nullable=False),
        sa.Column("conflict_notifications_enabled", sa.Boolean(), nullable=False),
        sa.Column("reauth_notifications_enabled", sa.Boolean(), nullable=False),
        sa.Column("quiet_hours_enabled", sa.Boolean(), nullable=False),
        sa.Column("quiet_start", sa.Time(), nullable=False),
        sa.Column("quiet_end", sa.Time(), nullable=False),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_table(
        "inbox_connection_states",
        sa.Column("connection_id", sa.UUID(), nullable=False),
        sa.Column("blocked", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("connection_id"),
    )
    op.create_table(
        "inbox_items",
        sa.Column("inbox_item_id", sa.UUID(), nullable=False),
        sa.Column("connection_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.String(length=120), nullable=False),
        sa.Column("source_type", sa.String(length=40), nullable=False),
        sa.Column("ingress_type", sa.String(length=40), nullable=False),
        sa.Column("trust_level", sa.String(length=10), nullable=False),
        sa.Column("external_id", sa.String(length=512), nullable=False),
        sa.Column("dedupe_key", sa.String(length=512), nullable=True),
        sa.Column("thread_id", sa.String(length=512), nullable=True),
        sa.Column("sender_id", sa.String(length=320), nullable=False),
        sa.Column("sender_display", sa.String(length=320), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_content_ref", sa.UUID(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("failure_class", sa.String(length=80), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("inbox_item_id"),
        sa.UniqueConstraint("connection_id", "dedupe_key", name="uq_inbox_connection_dedupe"),
        sa.UniqueConstraint("connection_id", "external_id", name="uq_inbox_connection_external"),
    )
    op.create_index(
        "ix_inbox_status_received", "inbox_items", ["status", "received_at"], unique=False
    )
    op.create_table(
        "inbox_raw_contents",
        sa.Column("raw_content_id", sa.UUID(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("body_text", sa.Text(), nullable=False),
        sa.Column("body_html", sa.Text(), nullable=True),
        sa.Column("mime_type", sa.String(length=80), nullable=False),
        sa.Column("recipients", postgresql.JSONB(astext_type=Text()), nullable=False),
        sa.Column("internet_message_id", sa.String(length=998), nullable=True),
        sa.Column("change_key", sa.String(length=512), nullable=True),
        sa.Column("has_attachments", sa.Boolean(), nullable=False),
        sa.Column(
            "attachment_metadata",
            postgresql.JSONB(astext_type=Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("raw_content_id"),
    )
    op.create_table(
        "inbox_source_deletions",
        sa.Column("connection_id", sa.UUID(), nullable=False),
        sa.Column("external_id", sa.String(length=512), nullable=False),
        sa.Column("dedupe_key", sa.String(length=512), nullable=True),
        sa.Column(
            "deleted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("connection_id", "external_id"),
    )
    op.create_index(
        op.f("ix_inbox_source_deletions_dedupe_key"),
        "inbox_source_deletions",
        ["dedupe_key"],
        unique=False,
    )
    op.create_table(
        "inbox_sync_cursors",
        sa.Column("connection_id", sa.UUID(), nullable=False),
        sa.Column("cursor_value", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("connection_id"),
    )
    op.create_table(
        "knowledge_sources",
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column("source_ref", sa.String(length=512), nullable=False),
        sa.Column("source_type", sa.String(length=40), nullable=False),
        sa.Column("source_version", sa.String(length=128), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("trust_level", sa.String(length=10), nullable=False),
        sa.Column("attributes", postgresql.JSONB(astext_type=Text()), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.PrimaryKeyConstraint("source_id"),
        sa.UniqueConstraint("source_ref", "source_version", name="uq_knowledge_source_version"),
    )
    op.create_index(
        "ix_knowledge_source_filter",
        "knowledge_sources",
        ["status", "source_type", "occurred_at"],
        unique=False,
    )
    op.create_table(
        "normalization_assets",
        sa.Column("asset_id", sa.UUID(), nullable=False),
        sa.Column("inbox_item_id", sa.UUID(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("parser_version", sa.String(length=120), nullable=False),
        sa.Column("source_ref", sa.String(length=512), nullable=True),
        sa.Column("calendar_payload", postgresql.JSONB(astext_type=Text()), nullable=True),
        sa.PrimaryKeyConstraint("asset_id"),
    )
    op.create_index(
        op.f("ix_normalization_assets_inbox_item_id"),
        "normalization_assets",
        ["inbox_item_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_normalization_assets_source_ref"),
        "normalization_assets",
        ["source_ref"],
        unique=False,
    )
    op.create_table(
        "normalization_contents",
        sa.Column("inbox_item_id", sa.UUID(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("normalizer_version", sa.String(length=80), nullable=False),
        sa.Column("source_ref", sa.String(length=512), nullable=True),
        sa.PrimaryKeyConstraint("inbox_item_id"),
    )
    op.create_index(
        op.f("ix_normalization_contents_source_ref"),
        "normalization_contents",
        ["source_ref"],
        unique=False,
    )
    op.create_table(
        "notifications_deliveries",
        sa.Column("idempotency_key", sa.String(length=240), nullable=False),
        sa.Column("delivery_id", sa.String(length=512), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("idempotency_key"),
    )
    op.create_table(
        "notifications_intents",
        sa.Column("intent_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.String(length=120), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("subject_key", sa.String(length=240), nullable=False),
        sa.Column("idempotency_key", sa.String(length=240), nullable=False),
        sa.Column("template_version", sa.String(length=80), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("state", sa.String(length=40), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("lease_owner", sa.String(length=120), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_delivery_id", sa.String(length=512), nullable=True),
        sa.Column("failure_class", sa.String(length=80), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("intent_id"),
        sa.UniqueConstraint("idempotency_key", name="uq_notifications_intent_idempotency"),
    )
    op.create_index(
        "ix_notifications_intent_due",
        "notifications_intents",
        ["state", "available_at"],
        unique=False,
    )
    op.create_index(
        "ix_notifications_intent_subject_sent",
        "notifications_intents",
        ["subject_key", "sent_at"],
        unique=False,
    )
    op.create_index(
        "uq_notifications_intent_blocking_subject",
        "notifications_intents",
        ["subject_key"],
        unique=True,
        postgresql_where=sa.text("state IN ('PENDING', 'LEASED', 'AMBIGUOUS', 'DEAD_LETTER')"),
    )
    op.create_table(
        "notifications_reminder_action_tokens",
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("owner_id", sa.String(length=120), nullable=False),
        sa.Column("reminder_id", sa.UUID(), nullable=False),
        sa.Column("agenda_entry_id", sa.UUID(), nullable=False),
        sa.Column("agenda_entry_version", sa.Integer(), nullable=False),
        sa.Column("occurrence", sa.Integer(), nullable=False),
        sa.Column("action_type", sa.String(length=80), nullable=False),
        sa.Column("action_value", sa.String(length=80), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome", sa.String(length=40), nullable=True),
        sa.PrimaryKeyConstraint("token_hash"),
    )
    op.create_index(
        "ix_notifications_reminder_action_tokens_expiry",
        "notifications_reminder_action_tokens",
        ["expires_at"],
        unique=False,
    )
    op.create_index(
        "uq_notifications_reminder_action_tokens_claim",
        "notifications_reminder_action_tokens",
        ["owner_id", "reminder_id", "occurrence"],
        unique=True,
        postgresql_where=sa.text("claimed_at IS NOT NULL"),
    )
    op.create_table(
        "notifications_reminder_suppressions",
        sa.Column("idempotency_key", sa.String(length=240), nullable=False),
        sa.Column("reason", sa.String(length=80), nullable=False),
        sa.Column("suppressed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("idempotency_key"),
    )
    op.create_table(
        "platform_jobs",
        sa.Column("job_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=100), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=Text()), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_owner", sa.String(length=120), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="5", nullable=False),
        sa.Column("last_error_class", sa.String(length=80), nullable=True),
        sa.Column("last_error_detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("job_id"),
        sa.UniqueConstraint("idempotency_key", name="uq_platform_jobs_idempotency"),
    )
    op.create_index(
        "ix_platform_jobs_due",
        "platform_jobs",
        ["status", "available_at", "lease_until"],
        unique=False,
    )
    op.create_table(
        "platform_outbox_events",
        sa.Column("event_id", sa.UUID(), nullable=False),
        sa.Column("event_type", sa.String(length=120), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("aggregate_ref", sa.String(length=200), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=Text()), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error_class", sa.String(length=80), nullable=True),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index(
        "ix_outbox_unpublished",
        "platform_outbox_events",
        ["published_at", "occurred_at"],
        unique=False,
    )
    op.create_table(
        "reminders_items",
        sa.Column("reminder_id", sa.UUID(), nullable=False),
        sa.Column("agenda_entry_id", sa.UUID(), nullable=False),
        sa.Column("agenda_entry_version", sa.Integer(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("lease_owner", sa.String(length=120), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivery_ref", sa.String(length=512), nullable=True),
        sa.Column("failure_class", sa.Text(), nullable=True),
        sa.Column("occurrence", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("reminder_id"),
        sa.UniqueConstraint("idempotency_key", name="uq_reminders_idempotency"),
    )
    op.create_index("ix_reminders_due", "reminders_items", ["status", "due_at"], unique=False)
    op.create_table(
        "scheduling_proposals",
        sa.Column("proposal_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.String(length=120), nullable=False),
        sa.Column("candidate_id", sa.UUID(), nullable=False),
        sa.Column("candidate_kind", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("recommended_slot", postgresql.JSONB(astext_type=Text()), nullable=True),
        sa.Column("alternative_slots", postgresql.JSONB(astext_type=Text()), nullable=False),
        sa.Column("conflicts", postgresql.JSONB(astext_type=Text()), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("assumptions", postgresql.ARRAY(Text()), nullable=False),
        sa.Column("source_refs", postgresql.ARRAY(Text()), nullable=False),
        sa.Column("source_ref", sa.String(length=512), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("constraint_snapshot", postgresql.JSONB(astext_type=Text()), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("proposal_id"),
        sa.UniqueConstraint("candidate_id", name="uq_scheduling_proposal_candidate"),
    )
    op.create_index(
        op.f("ix_scheduling_proposals_source_ref"),
        "scheduling_proposals",
        ["source_ref"],
        unique=False,
    )
    op.create_table(
        "task_projection_cursors",
        sa.Column("cursor_id", sa.UUID(), nullable=False),
        sa.Column("connection_id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("provider_list_ref", sa.String(length=1024), nullable=False),
        sa.Column("opaque_cursor", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("cursor_id"),
        sa.UniqueConstraint(
            "provider",
            "connection_id",
            "provider_list_ref",
            name="uq_task_projection_cursor_target",
        ),
    )
    op.create_table(
        "task_projection_mappings",
        sa.Column("mapping_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.String(length=120), nullable=False),
        sa.Column("agenda_entry_id", sa.UUID(), nullable=False),
        sa.Column("agenda_entry_version", sa.Integer(), nullable=False),
        sa.Column("connection_id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("provider_list_ref", sa.String(length=1024), nullable=False),
        sa.Column("provider_task_ref", sa.String(length=1024), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("provider_revision", sa.String(length=1024), nullable=True),
        sa.Column("last_projected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_observed_completion", sa.Boolean(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("mapping_id"),
        sa.UniqueConstraint(
            "provider", "connection_id", "agenda_entry_id", name="uq_task_projection_mapping_agenda"
        ),
        sa.UniqueConstraint(
            "provider",
            "connection_id",
            "provider_task_ref",
            name="uq_task_projection_mapping_external",
        ),
    )
    op.create_index(
        "ix_task_projection_mapping_status", "task_projection_mappings", ["status"], unique=False
    )
    op.create_table(
        "task_projection_targets",
        sa.Column("target_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.String(length=120), nullable=False),
        sa.Column("connection_id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("provider_list_ref", sa.String(length=1024), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("target_id"),
        sa.UniqueConstraint(
            "provider", "connection_id", name="uq_task_projection_target_connection"
        ),
    )
    op.create_table(
        "understanding_calendar_change_candidates",
        sa.Column("candidate_id", sa.UUID(), nullable=False),
        sa.Column("asset_id", sa.UUID(), nullable=False),
        sa.Column("inbox_item_id", sa.UUID(), nullable=False),
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
        sa.Column("participants", postgresql.ARRAY(Text()), nullable=False),
        sa.Column("recurrence_rule", sa.Text(), nullable=True),
        sa.Column("agenda_entry_id", sa.UUID(), nullable=True),
        sa.Column("parent_source_ref", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("candidate_id"),
        sa.UniqueConstraint("version_key", name="uq_understanding_calendar_version"),
    )
    op.create_index(
        op.f("ix_understanding_calendar_change_candidates_asset_id"),
        "understanding_calendar_change_candidates",
        ["asset_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_understanding_calendar_change_candidates_inbox_item_id"),
        "understanding_calendar_change_candidates",
        ["inbox_item_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_understanding_calendar_change_candidates_parent_source_ref"),
        "understanding_calendar_change_candidates",
        ["parent_source_ref"],
        unique=False,
    )
    op.create_index(
        "ix_understanding_calendar_event_sequence",
        "understanding_calendar_change_candidates",
        ["external_event_key", "sequence"],
        unique=False,
    )
    op.create_table(
        "understanding_candidates",
        sa.Column("candidate_id", sa.UUID(), nullable=False),
        sa.Column("inbox_item_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("timezone", sa.String(length=80), nullable=False),
        sa.Column("location", sa.String(length=300), nullable=True),
        sa.Column("participants", postgresql.ARRAY(Text()), nullable=False),
        sa.Column("estimated_duration_minutes", sa.Integer(), nullable=True),
        sa.Column("priority", sa.String(length=20), nullable=True),
        sa.Column("allowed_windows", postgresql.ARRAY(Text()), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("assumptions", postgresql.ARRAY(Text()), nullable=False),
        sa.Column("evidence", postgresql.ARRAY(Text()), nullable=False),
        sa.Column("source_refs", postgresql.ARRAY(Text()), nullable=False),
        sa.Column("source_ref", sa.String(length=512), nullable=False),
        sa.PrimaryKeyConstraint("candidate_id"),
        sa.UniqueConstraint("inbox_item_id", name="uq_understanding_candidate_inbox"),
    )
    op.create_index(
        op.f("ix_understanding_candidates_source_ref"),
        "understanding_candidates",
        ["source_ref"],
        unique=False,
    )
    op.create_table(
        "workflow_understanding_checkpoints",
        sa.Column("inbox_item_id", sa.UUID(), nullable=False),
        sa.Column("phase", sa.String(length=20), nullable=False),
        sa.Column("result_kind", sa.String(length=20), nullable=True),
        sa.Column("candidate_id", sa.UUID(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("review_reason", sa.String(length=120), nullable=True),
        sa.Column("model_calls", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("source_ref", sa.String(length=512), nullable=True),
        sa.PrimaryKeyConstraint("inbox_item_id"),
    )
    op.create_index(
        op.f("ix_workflow_understanding_checkpoints_source_ref"),
        "workflow_understanding_checkpoints",
        ["source_ref"],
        unique=False,
    )
    op.create_table(
        "agent_turn_segments",
        sa.Column("turn_id", sa.UUID(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("inbox_item_id", sa.UUID(), nullable=False),
        sa.Column("source_type", sa.String(length=40), nullable=False),
        sa.Column("trust_level", sa.String(length=10), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider_sequence", sa.BigInteger(), nullable=True),
        sa.Column("reference_hash", sa.String(length=64), nullable=True),
        sa.Column("content_chars", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "position >= 1 AND content_chars >= 0", name="ck_agent_turn_segments_size"
        ),
        sa.ForeignKeyConstraint(["turn_id"], ["agent_turn_batches.turn_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("turn_id", "position"),
        sa.UniqueConstraint("inbox_item_id", name="uq_agent_turn_segments_inbox_item"),
    )
    op.create_table(
        "data_lifecycle_purge_results",
        sa.Column("result_id", sa.UUID(), nullable=False),
        sa.Column("tombstone_id", sa.UUID(), nullable=False),
        sa.Column("module_name", sa.String(length=100), nullable=False),
        sa.Column("deleted_count", sa.Integer(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tombstone_id"], ["data_lifecycle_tombstones.tombstone_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("result_id"),
        sa.UniqueConstraint("tombstone_id", "module_name", name="uq_purge_result_module"),
    )
    op.create_table(
        "inbox_source_assets",
        sa.Column("asset_id", sa.UUID(), nullable=False),
        sa.Column("inbox_item_id", sa.UUID(), nullable=False),
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
        sa.CheckConstraint("actual_size IS NULL OR actual_size >= 0", name="ck_asset_actual_size"),
        sa.CheckConstraint(
            "declared_size IS NULL OR declared_size >= 0", name="ck_asset_declared_size"
        ),
        sa.ForeignKeyConstraint(
            ["inbox_item_id"], ["inbox_items.inbox_item_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("asset_id"),
        sa.UniqueConstraint(
            "inbox_item_id", "provider_asset_id", name="uq_inbox_assets_parent_provider"
        ),
    )
    op.create_index(
        "ix_inbox_assets_fetch_parse",
        "inbox_source_assets",
        ["fetch_status", "parse_status", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_inbox_assets_parent", "inbox_source_assets", ["inbox_item_id"], unique=False
    )
    op.create_index(
        "ix_inbox_assets_purge", "inbox_source_assets", ["purge_at", "deleted_at"], unique=False
    )
    op.create_table(
        "knowledge_chunks",
        sa.Column("chunk_id", sa.UUID(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("chunker_version", sa.String(length=80), nullable=False),
        sa.Column("index_version", sa.String(length=128), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["knowledge_sources.source_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("chunk_id"),
        sa.UniqueConstraint("source_id", "ordinal", name="uq_knowledge_chunk_ordinal"),
    )
    op.create_index(
        "ix_knowledge_chunk_content_trgm",
        "knowledge_chunks",
        ["content"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"content": "gin_trgm_ops"},
    )
    op.create_index("ix_knowledge_chunk_index", "knowledge_chunks", ["index_version"], unique=False)
    op.create_table(
        "knowledge_embeddings",
        sa.Column("chunk_id", sa.UUID(), nullable=False),
        sa.Column("model_id", sa.String(length=200), nullable=False),
        sa.Column("model_digest", sa.String(length=256), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("embedding", VECTOR(dim=1024), nullable=False),
        sa.ForeignKeyConstraint(["chunk_id"], ["knowledge_chunks.chunk_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("chunk_id"),
    )
    op.create_index(
        "ix_knowledge_embedding_hnsw",
        "knowledge_embeddings",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    op.drop_table("knowledge_embeddings")
    op.drop_table("knowledge_chunks")
    op.drop_table("inbox_source_assets")
    op.drop_table("data_lifecycle_purge_results")
    op.drop_table("agent_turn_segments")
    op.drop_table("workflow_understanding_checkpoints")
    op.drop_table("understanding_candidates")
    op.drop_table("understanding_calendar_change_candidates")
    op.drop_table("task_projection_targets")
    op.drop_table("task_projection_mappings")
    op.drop_table("task_projection_cursors")
    op.drop_table("scheduling_proposals")
    op.drop_table("reminders_items")
    op.drop_table("platform_outbox_events")
    op.drop_table("platform_jobs")
    op.drop_table("notifications_reminder_suppressions")
    op.drop_table("notifications_reminder_action_tokens")
    op.drop_table("notifications_intents")
    op.drop_table("notifications_deliveries")
    op.drop_table("normalization_contents")
    op.drop_table("normalization_assets")
    op.drop_table("knowledge_sources")
    op.drop_table("inbox_sync_cursors")
    op.drop_table("inbox_source_deletions")
    op.drop_table("inbox_raw_contents")
    op.drop_table("inbox_items")
    op.drop_table("inbox_connection_states")
    op.drop_table("identity_user_preferences")
    op.drop_table("identity_owner_group_aliases")
    op.drop_table("identity_mail_rules")
    op.drop_table("data_lifecycle_tombstones")
    op.drop_table("credentials_vault_records")
    op.drop_table("connections_oauth_transactions")
    op.drop_table("connections_external_connections")
    op.drop_table("audit_events")
    op.drop_table("ai_gateway_invocations")
    op.drop_table("agent_turn_batches")
    op.drop_table("agent_tool_calls")
    op.drop_table("agent_runs")
    op.drop_table("agent_run_events")
    op.drop_table("agent_event_cases")
    op.drop_table("agent_conversations")
    op.drop_table("agent_conversation_summaries")
    op.drop_table("agent_conversation_sequence_counters")
    op.drop_table("agent_conversation_events")
    op.drop_table("agent_context_items")
    op.drop_table("agenda_entries")
    op.drop_table("actions_requests")
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")
    op.execute("DROP EXTENSION IF EXISTS vector")
