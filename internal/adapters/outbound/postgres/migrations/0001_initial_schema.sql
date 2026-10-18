-- Generated from Alembic 0001_initial_schema; source SHA256: e9aed01b55126c37490f3511bbc33207a74428d31a48d2beba79b6536ee2ceec
-- Frozen export from Main@c63eae17adf4fc2cf26c694ae8ba7e7f23c93470; see baseline.json.
CREATE EXTENSION IF NOT EXISTS vector;

CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE actions_requests (
    action_id UUID NOT NULL,
    user_id VARCHAR(120) NOT NULL,
    action_type VARCHAR(30) NOT NULL,
    idempotency_key VARCHAR(200) NOT NULL,
    status VARCHAR(30) NOT NULL,
    requested_at TIMESTAMP WITH TIME ZONE NOT NULL,
    proposal_id UUID,
    proposal_version INTEGER,
    agenda_entry_id UUID,
    agenda_entry_version INTEGER,
    reminder_id UUID,
    failure_class VARCHAR(120),
    operation_payload JSONB,
    PRIMARY KEY (action_id),
    CONSTRAINT uq_actions_idempotency UNIQUE (idempotency_key)
);

CREATE TABLE agenda_entries (
    agenda_entry_id UUID NOT NULL,
    action_id UUID NOT NULL,
    idempotency_key VARCHAR(200) NOT NULL,
    kind VARCHAR(20) NOT NULL,
    title VARCHAR(300) NOT NULL,
    starts_at TIMESTAMP WITH TIME ZONE NOT NULL,
    ends_at TIMESTAMP WITH TIME ZONE NOT NULL,
    timezone VARCHAR(80) NOT NULL,
    status VARCHAR(20) NOT NULL,
    source_refs TEXT[] NOT NULL,
    proposal_id UUID NOT NULL,
    version INTEGER NOT NULL,
    last_operation_key VARCHAR(200) NOT NULL,
    PRIMARY KEY (agenda_entry_id),
    CONSTRAINT uq_agenda_idempotency UNIQUE (idempotency_key)
);

CREATE INDEX ix_agenda_active_range ON agenda_entries (status, starts_at, ends_at);

CREATE TABLE agent_context_items (
    scope_type VARCHAR(20) NOT NULL,
    scope_id UUID NOT NULL,
    inbox_item_id UUID NOT NULL,
    occurred_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (scope_type, scope_id, inbox_item_id)
);

CREATE INDEX ix_agent_context_items_scope_time ON agent_context_items (scope_type, scope_id, occurred_at);

CREATE TABLE agent_conversation_events (
    event_id UUID NOT NULL,
    scope_type VARCHAR(20) NOT NULL,
    scope_id UUID NOT NULL,
    user_id VARCHAR(120) NOT NULL,
    sequence INTEGER NOT NULL,
    event_type VARCHAR(40) NOT NULL,
    role VARCHAR(16) NOT NULL,
    occurred_at TIMESTAMP WITH TIME ZONE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    content TEXT NOT NULL,
    content_ref VARCHAR(160),
    content_hash VARCHAR(64) NOT NULL,
    delivery_status VARCHAR(16),
    run_id UUID,
    inbox_item_id UUID,
    notification_intent_id UUID,
    idempotency_key VARCHAR(255) NOT NULL,
    metadata JSONB NOT NULL,
    PRIMARY KEY (event_id),
    CONSTRAINT ck_agent_conversation_events_delivery CHECK (delivery_status IS NULL OR delivery_status IN ('DELIVERED', 'FAILED')),
    CONSTRAINT ck_agent_conversation_events_type CHECK (event_type IN ('USER_MESSAGE', 'AGENT_REPLY', 'TOOL_CALL', 'TOOL_RESULT', 'MAIL_NOTIFICATION', 'MAIL_DIGEST', 'DAILY_DIGEST', 'SYSTEM_RESULT')),
    CONSTRAINT ck_agent_conversation_events_role CHECK (role IN ('user', 'agent', 'tool', 'system')),
    CONSTRAINT ck_agent_conversation_events_scope CHECK (scope_type IN ('conversation', 'owner_timeline')),
    CONSTRAINT ck_agent_conversation_events_sequence CHECK (sequence >= 1),
    CONSTRAINT uq_agent_conversation_events_idempotency UNIQUE (idempotency_key),
    CONSTRAINT uq_agent_conversation_events_scope_sequence UNIQUE (scope_type, scope_id, sequence),
    CONSTRAINT uq_agent_conversation_events_user_sequence UNIQUE (user_id, sequence)
);

CREATE INDEX ix_agent_conversation_events_scope_time ON agent_conversation_events (scope_type, scope_id, occurred_at);

CREATE TABLE agent_conversation_sequence_counters (
    user_id VARCHAR(120) NOT NULL,
    last_sequence INTEGER NOT NULL,
    PRIMARY KEY (user_id)
);

CREATE TABLE agent_conversation_summaries (
    summary_id UUID NOT NULL,
    scope_type VARCHAR(20) NOT NULL,
    scope_id UUID NOT NULL,
    user_id VARCHAR(120) NOT NULL,
    summary_kind VARCHAR(40) NOT NULL,
    from_sequence INTEGER NOT NULL,
    to_sequence INTEGER NOT NULL,
    content TEXT NOT NULL,
    content_hash VARCHAR(64) NOT NULL,
    source_hash VARCHAR(64) NOT NULL,
    structured_json JSONB DEFAULT '{}' NOT NULL,
    idempotency_key VARCHAR(255) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (summary_id),
    CONSTRAINT ck_agent_conversation_summaries_scope CHECK (scope_type IN ('conversation', 'owner_timeline')),
    CONSTRAINT ck_agent_conversation_summaries_range CHECK (from_sequence >= 1 AND to_sequence >= from_sequence),
    CONSTRAINT uq_agent_conversation_summaries_idempotency UNIQUE (idempotency_key),
    CONSTRAINT uq_agent_conversation_summaries_range UNIQUE (scope_type, scope_id, from_sequence, to_sequence)
);

CREATE INDEX ix_agent_conversation_summaries_scope_to ON agent_conversation_summaries (scope_type, scope_id, to_sequence);

CREATE TABLE agent_conversations (
    conversation_id UUID NOT NULL,
    user_id VARCHAR(120) NOT NULL,
    channel VARCHAR(40) NOT NULL,
    conversation_key VARCHAR(512) NOT NULL,
    summary TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (conversation_id),
    CONSTRAINT uq_agent_conversation_scope UNIQUE (user_id, channel, conversation_key)
);

CREATE TABLE agent_event_cases (
    event_case_id UUID NOT NULL,
    user_id VARCHAR(120) NOT NULL,
    event_key VARCHAR(512) NOT NULL,
    summary TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (event_case_id),
    CONSTRAINT uq_agent_event_scope UNIQUE (user_id, event_key)
);

CREATE TABLE agent_run_events (
    event_id UUID NOT NULL,
    run_id UUID NOT NULL,
    sequence INTEGER NOT NULL,
    event_type VARCHAR(40) NOT NULL,
    step INTEGER NOT NULL,
    occurred_at TIMESTAMP WITH TIME ZONE NOT NULL,
    status VARCHAR(32),
    duration_ms INTEGER,
    error_class VARCHAR(120),
    tool_name VARCHAR(120),
    call_id VARCHAR(160),
    invocation_id UUID,
    idempotency_key VARCHAR(255) NOT NULL,
    metadata JSONB NOT NULL,
    PRIMARY KEY (event_id),
    CONSTRAINT uq_agent_run_events_idempotency UNIQUE (run_id, idempotency_key),
    CONSTRAINT uq_agent_run_events_sequence UNIQUE (run_id, sequence)
);

CREATE INDEX ix_agent_run_events_run_scope ON agent_run_events (run_id, sequence);

CREATE INDEX ix_agent_run_events_run_time ON agent_run_events (run_id, occurred_at);

CREATE TABLE agent_runs (
    run_id UUID NOT NULL,
    inbox_item_id UUID NOT NULL,
    user_id VARCHAR(120) NOT NULL,
    source_type VARCHAR(40) NOT NULL,
    status VARCHAR(32) NOT NULL,
    step INTEGER NOT NULL,
    observations JSONB NOT NULL,
    final_content TEXT,
    final_delivery VARCHAR(16),
    effective_delivery VARCHAR(16),
    failure_class VARCHAR(120),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    version INTEGER NOT NULL,
    conversation_id UUID,
    event_case_id UUID,
    execution_owner VARCHAR(160),
    execution_lease_until TIMESTAMP WITH TIME ZONE,
    execution_epoch INTEGER DEFAULT '0' NOT NULL,
    completed_at TIMESTAMP WITH TIME ZONE,
    context_revision INTEGER,
    context_max_sequence INTEGER,
    context_hash VARCHAR(64),
    source_refs JSONB NOT NULL,
    PRIMARY KEY (run_id),
    CONSTRAINT ck_agent_runs_effective_delivery CHECK (effective_delivery IS NULL OR effective_delivery IN ('HOLD', 'NOTIFY')),
    CONSTRAINT uq_agent_runs_inbox_item UNIQUE (inbox_item_id)
);

CREATE INDEX ix_agent_runs_completed ON agent_runs (completed_at);

CREATE INDEX ix_agent_runs_conversation_reply_time ON agent_runs (conversation_id, updated_at);

CREATE INDEX ix_agent_runs_event_reply_time ON agent_runs (event_case_id, updated_at);

CREATE INDEX ix_agent_runs_execution_lease ON agent_runs (status, execution_lease_until);

CREATE INDEX ix_agent_runs_status_updated ON agent_runs (status, updated_at);

CREATE TABLE agent_tool_calls (
    run_id UUID NOT NULL,
    call_id VARCHAR(160) NOT NULL,
    tool_name VARCHAR(120) NOT NULL,
    arguments_hash VARCHAR(128) NOT NULL,
    observation JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (run_id, call_id)
);

CREATE TABLE agent_turn_batches (
    turn_id UUID NOT NULL,
    user_id VARCHAR(120) NOT NULL,
    conversation_key_hash VARCHAR(64) NOT NULL,
    status VARCHAR(16) NOT NULL,
    generation INTEGER NOT NULL,
    message_count INTEGER NOT NULL,
    content_chars INTEGER NOT NULL,
    ready_at TIMESTAMP WITH TIME ZONE NOT NULL,
    hard_deadline_at TIMESTAMP WITH TIME ZONE NOT NULL,
    lease_owner VARCHAR(160),
    lease_until TIMESTAMP WITH TIME ZONE,
    failure_class VARCHAR(120),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (turn_id),
    CONSTRAINT ck_agent_turn_batches_status CHECK (status IN ('OPEN', 'LEASED', 'COMPLETED', 'FAILED')),
    CONSTRAINT ck_agent_turn_batches_counts CHECK (generation >= 1 AND message_count >= 1 AND content_chars >= 0)
);

CREATE INDEX ix_agent_turn_batches_conversation_status ON agent_turn_batches (conversation_key_hash, status, created_at);

CREATE TABLE ai_gateway_invocations (
    invocation_id UUID NOT NULL,
    use_case VARCHAR(80) NOT NULL,
    prompt_version VARCHAR(80) NOT NULL,
    route VARCHAR(20) NOT NULL,
    model VARCHAR(120),
    status VARCHAR(20) NOT NULL,
    failure_class VARCHAR(80),
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    started_at TIMESTAMP WITH TIME ZONE NOT NULL,
    completed_at TIMESTAMP WITH TIME ZONE NOT NULL,
    latency_ms INTEGER NOT NULL,
    PRIMARY KEY (invocation_id)
);

CREATE TABLE audit_events (
    audit_id UUID NOT NULL,
    event_type VARCHAR(100) NOT NULL,
    actor_ref VARCHAR(120) NOT NULL,
    subject_ref VARCHAR(512) NOT NULL,
    outcome VARCHAR(40) NOT NULL,
    occurred_at TIMESTAMP WITH TIME ZONE NOT NULL,
    metadata JSONB NOT NULL,
    PRIMARY KEY (audit_id)
);

CREATE INDEX ix_audit_event_time ON audit_events (event_type, occurred_at);

CREATE TABLE connections_external_connections (
    connection_id UUID NOT NULL,
    user_id VARCHAR(120) NOT NULL,
    provider VARCHAR(40) NOT NULL,
    status VARCHAR(40) NOT NULL,
    provider_account_id VARCHAR(200),
    account_mask VARCHAR(240),
    account_fingerprint VARCHAR(80),
    display_label VARCHAR(120) NOT NULL,
    is_default BOOLEAN NOT NULL,
    sync_enabled BOOLEAN NOT NULL,
    capabilities JSONB NOT NULL,
    credential_ref UUID,
    last_synced_at TIMESTAMP WITH TIME ZONE,
    reauth_epoch INTEGER NOT NULL,
    reauth_required_since TIMESTAMP WITH TIME ZONE,
    version INTEGER NOT NULL,
    PRIMARY KEY (connection_id)
);

CREATE INDEX ix_connections_user_provider ON connections_external_connections (user_id, provider);

CREATE UNIQUE INDEX uq_connections_active_identity ON connections_external_connections (user_id, provider, account_fingerprint) WHERE account_fingerprint IS NOT NULL AND status != 'DISCONNECTED';

CREATE UNIQUE INDEX uq_connections_default_provider ON connections_external_connections (user_id, provider) WHERE is_default IS TRUE AND status IN ('ACTIVE', 'DEGRADED', 'REAUTH_REQUIRED');

CREATE TABLE connections_oauth_transactions (
    transaction_id UUID NOT NULL,
    connection_id UUID NOT NULL,
    user_id VARCHAR(120) NOT NULL,
    state_hash BYTEA NOT NULL,
    browser_session_hash BYTEA NOT NULL,
    flow_credential_ref UUID NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    consumed_at TIMESTAMP WITH TIME ZONE,
    PRIMARY KEY (transaction_id),
    UNIQUE (state_hash)
);

CREATE INDEX ix_connections_oauth_claim ON connections_oauth_transactions (state_hash, expires_at, consumed_at);

CREATE TABLE credentials_vault_records (
    credential_id UUID NOT NULL,
    kind VARCHAR(40) NOT NULL,
    key_version INTEGER NOT NULL,
    nonce BYTEA NOT NULL,
    ciphertext BYTEA NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE,
    PRIMARY KEY (credential_id)
);

CREATE TABLE data_lifecycle_tombstones (
    tombstone_id UUID NOT NULL,
    subject_ref VARCHAR(512) NOT NULL,
    requested_at TIMESTAMP WITH TIME ZONE NOT NULL,
    purge_by TIMESTAMP WITH TIME ZONE NOT NULL,
    status VARCHAR(30) NOT NULL,
    completed_at TIMESTAMP WITH TIME ZONE,
    PRIMARY KEY (tombstone_id),
    CONSTRAINT uq_lifecycle_tombstone_subject UNIQUE (subject_ref)
);

CREATE TABLE identity_mail_rules (
    rule_id UUID NOT NULL,
    user_id VARCHAR(120) NOT NULL,
    match_field VARCHAR(20) NOT NULL,
    pattern VARCHAR(240) NOT NULL,
    normalized_pattern VARCHAR(240) NOT NULL,
    action VARCHAR(10) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (rule_id),
    CONSTRAINT ck_mail_rules_action CHECK (action IN ('NOTIFY', 'HOLD')),
    CONSTRAINT ck_mail_rules_match_field CHECK (match_field IN ('SENDER', 'SUBJECT')),
    CONSTRAINT identity_mail_rules_user_id_match_field_normalized_pattern_key UNIQUE (user_id, match_field, normalized_pattern)
);

CREATE INDEX ix_identity_mail_rules_user ON identity_mail_rules (user_id, created_at);

CREATE TABLE identity_owner_group_aliases (
    user_id VARCHAR(120) NOT NULL,
    normalized_alias VARCHAR(128) NOT NULL,
    alias VARCHAR(128) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (user_id, normalized_alias)
);

CREATE TABLE identity_user_preferences (
    user_id VARCHAR(120) NOT NULL,
    timezone VARCHAR(80) NOT NULL,
    work_start TIME WITHOUT TIME ZONE NOT NULL,
    work_end TIME WITHOUT TIME ZONE NOT NULL,
    lunch_start TIME WITHOUT TIME ZONE NOT NULL,
    lunch_end TIME WITHOUT TIME ZONE NOT NULL,
    working_weekdays INTEGER[] NOT NULL,
    default_event_minutes INTEGER NOT NULL,
    default_task_minutes INTEGER NOT NULL,
    digest_enabled BOOLEAN NOT NULL,
    digest_local_time TIME WITHOUT TIME ZONE NOT NULL,
    conflict_notifications_enabled BOOLEAN NOT NULL,
    reauth_notifications_enabled BOOLEAN NOT NULL,
    quiet_hours_enabled BOOLEAN NOT NULL,
    quiet_start TIME WITHOUT TIME ZONE NOT NULL,
    quiet_end TIME WITHOUT TIME ZONE NOT NULL,
    PRIMARY KEY (user_id)
);

CREATE TABLE inbox_connection_states (
    connection_id UUID NOT NULL,
    blocked BOOLEAN NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (connection_id)
);

CREATE TABLE inbox_items (
    inbox_item_id UUID NOT NULL,
    connection_id UUID NOT NULL,
    user_id VARCHAR(120) NOT NULL,
    source_type VARCHAR(40) NOT NULL,
    ingress_type VARCHAR(40) NOT NULL,
    trust_level VARCHAR(10) NOT NULL,
    external_id VARCHAR(512) NOT NULL,
    dedupe_key VARCHAR(512),
    thread_id VARCHAR(512),
    sender_id VARCHAR(320) NOT NULL,
    sender_display VARCHAR(320),
    occurred_at TIMESTAMP WITH TIME ZONE NOT NULL,
    received_at TIMESTAMP WITH TIME ZONE NOT NULL,
    raw_content_ref UUID NOT NULL,
    content_hash VARCHAR(64) NOT NULL,
    status VARCHAR(40) NOT NULL,
    failure_class VARCHAR(80),
    retry_count INTEGER NOT NULL,
    version INTEGER NOT NULL,
    deleted_at TIMESTAMP WITH TIME ZONE,
    PRIMARY KEY (inbox_item_id),
    CONSTRAINT uq_inbox_connection_dedupe UNIQUE (connection_id, dedupe_key),
    CONSTRAINT uq_inbox_connection_external UNIQUE (connection_id, external_id)
);

CREATE INDEX ix_inbox_status_received ON inbox_items (status, received_at);

CREATE TABLE inbox_raw_contents (
    raw_content_id UUID NOT NULL,
    subject TEXT NOT NULL,
    body_text TEXT NOT NULL,
    body_html TEXT,
    mime_type VARCHAR(80) NOT NULL,
    recipients JSONB NOT NULL,
    internet_message_id VARCHAR(998),
    change_key VARCHAR(512),
    has_attachments BOOLEAN NOT NULL,
    attachment_metadata JSONB DEFAULT '[]' NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (raw_content_id)
);

CREATE TABLE inbox_source_deletions (
    connection_id UUID NOT NULL,
    external_id VARCHAR(512) NOT NULL,
    dedupe_key VARCHAR(512),
    deleted_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (connection_id, external_id)
);

CREATE INDEX ix_inbox_source_deletions_dedupe_key ON inbox_source_deletions (dedupe_key);

CREATE TABLE inbox_sync_cursors (
    connection_id UUID NOT NULL,
    cursor_value TEXT NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (connection_id)
);

CREATE TABLE knowledge_sources (
    source_id UUID NOT NULL,
    source_ref VARCHAR(512) NOT NULL,
    source_type VARCHAR(40) NOT NULL,
    source_version VARCHAR(128) NOT NULL,
    occurred_at TIMESTAMP WITH TIME ZONE NOT NULL,
    trust_level VARCHAR(10) NOT NULL,
    attributes JSONB NOT NULL,
    status VARCHAR(20) NOT NULL,
    PRIMARY KEY (source_id),
    CONSTRAINT uq_knowledge_source_version UNIQUE (source_ref, source_version)
);

CREATE INDEX ix_knowledge_source_filter ON knowledge_sources (status, source_type, occurred_at);

CREATE TABLE normalization_assets (
    asset_id UUID NOT NULL,
    inbox_item_id UUID NOT NULL,
    text TEXT NOT NULL,
    source_hash VARCHAR(64) NOT NULL,
    parser_version VARCHAR(120) NOT NULL,
    source_ref VARCHAR(512),
    calendar_payload JSONB,
    PRIMARY KEY (asset_id)
);

CREATE INDEX ix_normalization_assets_inbox_item_id ON normalization_assets (inbox_item_id);

CREATE INDEX ix_normalization_assets_source_ref ON normalization_assets (source_ref);

CREATE TABLE normalization_contents (
    inbox_item_id UUID NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    source_hash VARCHAR(64) NOT NULL,
    normalizer_version VARCHAR(80) NOT NULL,
    source_ref VARCHAR(512),
    PRIMARY KEY (inbox_item_id)
);

CREATE INDEX ix_normalization_contents_source_ref ON normalization_contents (source_ref);

CREATE TABLE notifications_deliveries (
    idempotency_key VARCHAR(240) NOT NULL,
    delivery_id VARCHAR(512) NOT NULL,
    sent_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (idempotency_key)
);

CREATE TABLE notifications_intents (
    intent_id UUID NOT NULL,
    user_id VARCHAR(120) NOT NULL,
    kind VARCHAR(40) NOT NULL,
    subject_key VARCHAR(240) NOT NULL,
    idempotency_key VARCHAR(240) NOT NULL,
    template_version VARCHAR(80) NOT NULL,
    content TEXT NOT NULL,
    state VARCHAR(40) NOT NULL,
    available_at TIMESTAMP WITH TIME ZONE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    attempt_count INTEGER NOT NULL,
    lease_owner VARCHAR(120),
    lease_until TIMESTAMP WITH TIME ZONE,
    provider_delivery_id VARCHAR(512),
    failure_class VARCHAR(80),
    sent_at TIMESTAMP WITH TIME ZONE,
    version INTEGER NOT NULL,
    PRIMARY KEY (intent_id),
    CONSTRAINT uq_notifications_intent_idempotency UNIQUE (idempotency_key)
);

CREATE INDEX ix_notifications_intent_due ON notifications_intents (state, available_at);

CREATE INDEX ix_notifications_intent_subject_sent ON notifications_intents (subject_key, sent_at);

CREATE UNIQUE INDEX uq_notifications_intent_blocking_subject ON notifications_intents (subject_key) WHERE state IN ('PENDING', 'LEASED', 'AMBIGUOUS', 'DEAD_LETTER');

CREATE TABLE notifications_reminder_action_tokens (
    token_hash VARCHAR(128) NOT NULL,
    owner_id VARCHAR(120) NOT NULL,
    reminder_id UUID NOT NULL,
    agenda_entry_id UUID NOT NULL,
    agenda_entry_version INTEGER NOT NULL,
    occurrence INTEGER NOT NULL,
    action_type VARCHAR(80) NOT NULL,
    action_value VARCHAR(80),
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    used_at TIMESTAMP WITH TIME ZONE,
    claimed_at TIMESTAMP WITH TIME ZONE,
    resolved_at TIMESTAMP WITH TIME ZONE,
    outcome VARCHAR(40),
    PRIMARY KEY (token_hash)
);

CREATE INDEX ix_notifications_reminder_action_tokens_expiry ON notifications_reminder_action_tokens (expires_at);

CREATE UNIQUE INDEX uq_notifications_reminder_action_tokens_claim ON notifications_reminder_action_tokens (owner_id, reminder_id, occurrence) WHERE claimed_at IS NOT NULL;

CREATE TABLE notifications_reminder_suppressions (
    idempotency_key VARCHAR(240) NOT NULL,
    reason VARCHAR(80) NOT NULL,
    suppressed_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (idempotency_key)
);

CREATE TABLE platform_jobs (
    job_id UUID NOT NULL,
    kind VARCHAR(100) NOT NULL,
    payload JSONB NOT NULL,
    status VARCHAR(30) NOT NULL,
    idempotency_key VARCHAR(200) NOT NULL,
    available_at TIMESTAMP WITH TIME ZONE NOT NULL,
    lease_owner VARCHAR(120),
    lease_until TIMESTAMP WITH TIME ZONE,
    attempt_count INTEGER DEFAULT '0' NOT NULL,
    max_attempts INTEGER DEFAULT '5' NOT NULL,
    last_error_class VARCHAR(80),
    last_error_detail TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (job_id),
    CONSTRAINT uq_platform_jobs_idempotency UNIQUE (idempotency_key)
);

CREATE INDEX ix_platform_jobs_due ON platform_jobs (status, available_at, lease_until);

CREATE TABLE platform_outbox_events (
    event_id UUID NOT NULL,
    event_type VARCHAR(120) NOT NULL,
    schema_version INTEGER NOT NULL,
    aggregate_ref VARCHAR(200) NOT NULL,
    payload JSONB NOT NULL,
    occurred_at TIMESTAMP WITH TIME ZONE NOT NULL,
    published_at TIMESTAMP WITH TIME ZONE,
    attempt_count INTEGER DEFAULT '0' NOT NULL,
    last_error_class VARCHAR(80),
    PRIMARY KEY (event_id)
);

CREATE INDEX ix_outbox_unpublished ON platform_outbox_events (published_at, occurred_at);

CREATE TABLE reminders_items (
    reminder_id UUID NOT NULL,
    agenda_entry_id UUID NOT NULL,
    agenda_entry_version INTEGER NOT NULL,
    due_at TIMESTAMP WITH TIME ZONE NOT NULL,
    idempotency_key VARCHAR(200) NOT NULL,
    status VARCHAR(30) NOT NULL,
    attempt_count INTEGER NOT NULL,
    max_attempts INTEGER NOT NULL,
    lease_owner VARCHAR(120),
    lease_until TIMESTAMP WITH TIME ZONE,
    delivery_ref VARCHAR(512),
    failure_class TEXT,
    occurrence INTEGER NOT NULL,
    PRIMARY KEY (reminder_id),
    CONSTRAINT uq_reminders_idempotency UNIQUE (idempotency_key)
);

CREATE INDEX ix_reminders_due ON reminders_items (status, due_at);

CREATE TABLE scheduling_proposals (
    proposal_id UUID NOT NULL,
    user_id VARCHAR(120) NOT NULL,
    candidate_id UUID NOT NULL,
    candidate_kind VARCHAR(20) NOT NULL,
    title VARCHAR(300) NOT NULL,
    recommended_slot JSONB,
    alternative_slots JSONB NOT NULL,
    conflicts JSONB NOT NULL,
    rationale TEXT NOT NULL,
    assumptions TEXT[] NOT NULL,
    source_refs TEXT[] NOT NULL,
    source_ref VARCHAR(512) NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    constraint_snapshot JSONB NOT NULL,
    status VARCHAR(30) NOT NULL,
    version INTEGER NOT NULL,
    PRIMARY KEY (proposal_id),
    CONSTRAINT uq_scheduling_proposal_candidate UNIQUE (candidate_id)
);

CREATE INDEX ix_scheduling_proposals_source_ref ON scheduling_proposals (source_ref);

CREATE TABLE task_projection_cursors (
    cursor_id UUID NOT NULL,
    connection_id UUID NOT NULL,
    provider VARCHAR(40) NOT NULL,
    provider_list_ref VARCHAR(1024) NOT NULL,
    opaque_cursor TEXT NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    version INTEGER NOT NULL,
    PRIMARY KEY (cursor_id),
    CONSTRAINT uq_task_projection_cursor_target UNIQUE (provider, connection_id, provider_list_ref)
);

CREATE TABLE task_projection_mappings (
    mapping_id UUID NOT NULL,
    user_id VARCHAR(120) NOT NULL,
    agenda_entry_id UUID NOT NULL,
    agenda_entry_version INTEGER NOT NULL,
    connection_id UUID NOT NULL,
    provider VARCHAR(40) NOT NULL,
    provider_list_ref VARCHAR(1024) NOT NULL,
    provider_task_ref VARCHAR(1024),
    status VARCHAR(40) NOT NULL,
    provider_revision VARCHAR(1024),
    last_projected_at TIMESTAMP WITH TIME ZONE,
    last_checked_at TIMESTAMP WITH TIME ZONE,
    last_observed_completion BOOLEAN,
    version INTEGER NOT NULL,
    PRIMARY KEY (mapping_id),
    CONSTRAINT uq_task_projection_mapping_agenda UNIQUE (provider, connection_id, agenda_entry_id),
    CONSTRAINT uq_task_projection_mapping_external UNIQUE (provider, connection_id, provider_task_ref)
);

CREATE INDEX ix_task_projection_mapping_status ON task_projection_mappings (status);

CREATE TABLE task_projection_targets (
    target_id UUID NOT NULL,
    user_id VARCHAR(120) NOT NULL,
    connection_id UUID NOT NULL,
    provider VARCHAR(40) NOT NULL,
    provider_list_ref VARCHAR(1024) NOT NULL,
    display_name VARCHAR(120) NOT NULL,
    status VARCHAR(40) NOT NULL,
    resolved_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    version INTEGER NOT NULL,
    PRIMARY KEY (target_id),
    CONSTRAINT uq_task_projection_target_connection UNIQUE (provider, connection_id)
);

CREATE TABLE understanding_calendar_change_candidates (
    candidate_id UUID NOT NULL,
    asset_id UUID NOT NULL,
    inbox_item_id UUID NOT NULL,
    external_event_key VARCHAR(64) NOT NULL,
    version_key VARCHAR(64) NOT NULL,
    sequence INTEGER NOT NULL,
    change_kind VARCHAR(20) NOT NULL,
    state VARCHAR(40) NOT NULL,
    title TEXT NOT NULL,
    starts_at TIMESTAMP WITH TIME ZONE,
    ends_at TIMESTAMP WITH TIME ZONE,
    timezone VARCHAR(80) NOT NULL,
    location TEXT,
    participants TEXT[] NOT NULL,
    recurrence_rule TEXT,
    agenda_entry_id UUID,
    parent_source_ref VARCHAR(512),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (candidate_id),
    CONSTRAINT uq_understanding_calendar_version UNIQUE (version_key)
);

CREATE INDEX ix_understanding_calendar_change_candidates_asset_id ON understanding_calendar_change_candidates (asset_id);

CREATE INDEX ix_understanding_calendar_change_candidates_inbox_item_id ON understanding_calendar_change_candidates (inbox_item_id);

CREATE INDEX ix_understanding_calendar_change_candidates_parent_source_ref ON understanding_calendar_change_candidates (parent_source_ref);

CREATE INDEX ix_understanding_calendar_event_sequence ON understanding_calendar_change_candidates (external_event_key, sequence);

CREATE TABLE understanding_candidates (
    candidate_id UUID NOT NULL,
    inbox_item_id UUID NOT NULL,
    kind VARCHAR(20) NOT NULL,
    title VARCHAR(300) NOT NULL,
    starts_at TIMESTAMP WITH TIME ZONE,
    ends_at TIMESTAMP WITH TIME ZONE,
    deadline TIMESTAMP WITH TIME ZONE,
    timezone VARCHAR(80) NOT NULL,
    location VARCHAR(300),
    participants TEXT[] NOT NULL,
    estimated_duration_minutes INTEGER,
    priority VARCHAR(20),
    allowed_windows TEXT[] NOT NULL,
    confidence FLOAT NOT NULL,
    assumptions TEXT[] NOT NULL,
    evidence TEXT[] NOT NULL,
    source_refs TEXT[] NOT NULL,
    source_ref VARCHAR(512) NOT NULL,
    PRIMARY KEY (candidate_id),
    CONSTRAINT uq_understanding_candidate_inbox UNIQUE (inbox_item_id)
);

CREATE INDEX ix_understanding_candidates_source_ref ON understanding_candidates (source_ref);

CREATE TABLE workflow_understanding_checkpoints (
    inbox_item_id UUID NOT NULL,
    phase VARCHAR(20) NOT NULL,
    result_kind VARCHAR(20),
    candidate_id UUID,
    confidence FLOAT,
    review_reason VARCHAR(120),
    model_calls INTEGER NOT NULL,
    version INTEGER NOT NULL,
    source_ref VARCHAR(512),
    PRIMARY KEY (inbox_item_id)
);

CREATE INDEX ix_workflow_understanding_checkpoints_source_ref ON workflow_understanding_checkpoints (source_ref);

CREATE TABLE agent_turn_segments (
    turn_id UUID NOT NULL,
    position INTEGER NOT NULL,
    inbox_item_id UUID NOT NULL,
    source_type VARCHAR(40) NOT NULL,
    trust_level VARCHAR(10) NOT NULL,
    occurred_at TIMESTAMP WITH TIME ZONE NOT NULL,
    provider_sequence BIGINT,
    reference_hash VARCHAR(64),
    content_chars INTEGER NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (turn_id, position),
    CONSTRAINT ck_agent_turn_segments_size CHECK (position >= 1 AND content_chars >= 0),
    FOREIGN KEY(turn_id) REFERENCES agent_turn_batches (turn_id) ON DELETE CASCADE,
    CONSTRAINT uq_agent_turn_segments_inbox_item UNIQUE (inbox_item_id)
);

CREATE TABLE data_lifecycle_purge_results (
    result_id UUID NOT NULL,
    tombstone_id UUID NOT NULL,
    module_name VARCHAR(100) NOT NULL,
    deleted_count INTEGER NOT NULL,
    completed_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (result_id),
    FOREIGN KEY(tombstone_id) REFERENCES data_lifecycle_tombstones (tombstone_id) ON DELETE CASCADE,
    CONSTRAINT uq_purge_result_module UNIQUE (tombstone_id, module_name)
);

CREATE TABLE inbox_source_assets (
    asset_id UUID NOT NULL,
    inbox_item_id UUID NOT NULL,
    provider_asset_id VARCHAR(512) NOT NULL,
    provider_locator VARCHAR(512) NOT NULL,
    kind VARCHAR(40) NOT NULL,
    filename VARCHAR(512),
    declared_content_type VARCHAR(255) NOT NULL,
    detected_content_type VARCHAR(255),
    declared_size INTEGER,
    transfer_encoding VARCHAR(40),
    actual_size INTEGER,
    content_sha256 VARCHAR(64),
    storage_key VARCHAR(80),
    trust_level VARCHAR(10) NOT NULL,
    fetch_status VARCHAR(40) NOT NULL,
    parse_status VARCHAR(40) NOT NULL,
    parser_version VARCHAR(120),
    failure_class VARCHAR(80),
    purge_at TIMESTAMP WITH TIME ZONE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    fetched_at TIMESTAMP WITH TIME ZONE,
    parsed_at TIMESTAMP WITH TIME ZONE,
    deleted_at TIMESTAMP WITH TIME ZONE,
    version INTEGER NOT NULL,
    PRIMARY KEY (asset_id),
    CONSTRAINT ck_inbox_assets_t2 CHECK (trust_level = 'T2'),
    CONSTRAINT ck_asset_actual_size CHECK (actual_size IS NULL OR actual_size >= 0),
    CONSTRAINT ck_asset_declared_size CHECK (declared_size IS NULL OR declared_size >= 0),
    FOREIGN KEY(inbox_item_id) REFERENCES inbox_items (inbox_item_id) ON DELETE CASCADE,
    CONSTRAINT uq_inbox_assets_parent_provider UNIQUE (inbox_item_id, provider_asset_id)
);

CREATE INDEX ix_inbox_assets_fetch_parse ON inbox_source_assets (fetch_status, parse_status, created_at);

CREATE INDEX ix_inbox_assets_parent ON inbox_source_assets (inbox_item_id);

CREATE INDEX ix_inbox_assets_purge ON inbox_source_assets (purge_at, deleted_at);

CREATE TABLE knowledge_chunks (
    chunk_id UUID NOT NULL,
    source_id UUID NOT NULL,
    ordinal INTEGER NOT NULL,
    content TEXT NOT NULL,
    content_hash VARCHAR(64) NOT NULL,
    chunker_version VARCHAR(80) NOT NULL,
    index_version VARCHAR(128) NOT NULL,
    PRIMARY KEY (chunk_id),
    FOREIGN KEY(source_id) REFERENCES knowledge_sources (source_id) ON DELETE CASCADE,
    CONSTRAINT uq_knowledge_chunk_ordinal UNIQUE (source_id, ordinal)
);

CREATE INDEX ix_knowledge_chunk_content_trgm ON knowledge_chunks USING gin (content gin_trgm_ops);

CREATE INDEX ix_knowledge_chunk_index ON knowledge_chunks (index_version);

CREATE TABLE knowledge_embeddings (
    chunk_id UUID NOT NULL,
    model_id VARCHAR(200) NOT NULL,
    model_digest VARCHAR(256) NOT NULL,
    dimensions INTEGER NOT NULL,
    embedding VECTOR(1024) NOT NULL,
    PRIMARY KEY (chunk_id),
    FOREIGN KEY(chunk_id) REFERENCES knowledge_chunks (chunk_id) ON DELETE CASCADE
);

CREATE INDEX ix_knowledge_embedding_hnsw ON knowledge_embeddings USING hnsw (embedding vector_cosine_ops);

CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL, CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num));
INSERT INTO alembic_version (version_num) VALUES ('0001_initial_schema');
