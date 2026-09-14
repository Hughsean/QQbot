"""Tables owned by the Agent runtime."""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class AgentBase(DeclarativeBase):
    pass


class AgentRunRow(AgentBase):
    __tablename__ = "agent_runs"
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    inbox_item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    user_id: Mapped[str] = mapped_column(String(120), nullable=False)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    step: Mapped[int] = mapped_column(Integer, nullable=False)
    observations: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    final_content: Mapped[str | None] = mapped_column(Text)
    final_delivery: Mapped[str | None] = mapped_column(String(16))
    effective_delivery: Mapped[str | None] = mapped_column(String(16))
    failure_class: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    event_case_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    execution_owner: Mapped[str | None] = mapped_column(String(160))
    execution_lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    execution_epoch: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    context_revision: Mapped[int | None] = mapped_column(Integer)
    context_max_sequence: Mapped[int | None] = mapped_column(Integer)
    context_hash: Mapped[str | None] = mapped_column(String(64))
    source_refs: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    __table_args__ = (
        UniqueConstraint("inbox_item_id", name="uq_agent_runs_inbox_item"),
        CheckConstraint(
            "effective_delivery IS NULL OR effective_delivery IN ('HOLD', 'NOTIFY')",
            name="ck_agent_runs_effective_delivery",
        ),
        Index("ix_agent_runs_status_updated", "status", "updated_at"),
        Index("ix_agent_runs_completed", "completed_at"),
        Index("ix_agent_runs_conversation_reply_time", "conversation_id", "updated_at"),
        Index("ix_agent_runs_event_reply_time", "event_case_id", "updated_at"),
        Index("ix_agent_runs_execution_lease", "status", "execution_lease_until"),
    )


class AgentRunEventRow(AgentBase):
    __tablename__ = "agent_run_events"
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    step: Mapped[int] = mapped_column(Integer, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str | None] = mapped_column(String(32))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    error_class: Mapped[str | None] = mapped_column(String(120))
    tool_name: Mapped[str | None] = mapped_column(String(120))
    call_id: Mapped[str | None] = mapped_column(String(160))
    invocation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    metadata_json: Mapped[dict[str, object]] = mapped_column("metadata", JSONB, nullable=False)
    __table_args__ = (
        UniqueConstraint("run_id", "sequence", name="uq_agent_run_events_sequence"),
        UniqueConstraint("run_id", "idempotency_key", name="uq_agent_run_events_idempotency"),
        Index("ix_agent_run_events_run_time", "run_id", "occurred_at"),
        Index("ix_agent_run_events_run_scope", "run_id", "sequence"),
    )


class AgentToolCallRow(AgentBase):
    __tablename__ = "agent_tool_calls"
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    call_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    tool_name: Mapped[str] = mapped_column(String(120), nullable=False)
    arguments_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    observation: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ConversationRow(AgentBase):
    __tablename__ = "agent_conversations"
    conversation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(120), nullable=False)
    channel: Mapped[str] = mapped_column(String(40), nullable=False)
    conversation_key: Mapped[str] = mapped_column(String(512), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        UniqueConstraint(
            "user_id", "channel", "conversation_key", name="uq_agent_conversation_scope"
        ),
    )


_TURN_STATUS_CHECK = "status IN ('OPEN', 'LEASED', 'COMPLETED', 'FAILED')"


class AgentTurnBatchRow(AgentBase):
    """Durable quiet-window batch; conversation keys are stored only as hashes."""

    __tablename__ = "agent_turn_batches"
    turn_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(120), nullable=False)
    conversation_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    message_count: Mapped[int] = mapped_column(Integer, nullable=False)
    content_chars: Mapped[int] = mapped_column(Integer, nullable=False)
    ready_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    hard_deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lease_owner: Mapped[str | None] = mapped_column(String(160))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_class: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        CheckConstraint(_TURN_STATUS_CHECK, name="ck_agent_turn_batches_status"),
        CheckConstraint(
            "generation >= 1 AND message_count >= 1 AND content_chars >= 0",
            name="ck_agent_turn_batches_counts",
        ),
        Index(
            "ix_agent_turn_batches_conversation_status",
            "conversation_key_hash",
            "status",
            "created_at",
        ),
    )


class AgentTurnSegmentRow(AgentBase):
    __tablename__ = "agent_turn_segments"
    turn_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_turn_batches.turn_id", ondelete="CASCADE"),
        primary_key=True,
    )
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    inbox_item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    trust_level: Mapped[str] = mapped_column(String(10), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    provider_sequence: Mapped[int | None] = mapped_column(BigInteger)
    reference_hash: Mapped[str | None] = mapped_column(String(64))
    content_chars: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        UniqueConstraint("inbox_item_id", name="uq_agent_turn_segments_inbox_item"),
        CheckConstraint("position >= 1 AND content_chars >= 0", name="ck_agent_turn_segments_size"),
    )


class EventCaseRow(AgentBase):
    __tablename__ = "agent_event_cases"
    event_case_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(120), nullable=False)
    event_key: Mapped[str] = mapped_column(String(512), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (UniqueConstraint("user_id", "event_key", name="uq_agent_event_scope"),)


class ContextItemRow(AgentBase):
    __tablename__ = "agent_context_items"
    __table_args__ = (
        Index("ix_agent_context_items_scope_time", "scope_type", "scope_id", "occurred_at"),
    )
    scope_type: Mapped[str] = mapped_column(String(20), primary_key=True)
    scope_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    inbox_item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ConversationSequenceRow(AgentBase):
    """Per-user monotonic sequence counter shared by all timeline scopes."""

    __tablename__ = "agent_conversation_sequence_counters"
    user_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    last_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


_EVENT_TYPE_CHECK = (
    "event_type IN ('USER_MESSAGE', 'AGENT_REPLY', 'TOOL_CALL', 'TOOL_RESULT', "
    "'MAIL_NOTIFICATION', 'MAIL_DIGEST', 'DAILY_DIGEST', 'SYSTEM_RESULT')"
)
_ROLE_CHECK = "role IN ('user', 'agent', 'tool', 'system')"
_SCOPE_CHECK = "scope_type IN ('conversation', 'owner_timeline')"
_DELIVERY_CHECK = "delivery_status IS NULL OR delivery_status IN ('DELIVERED', 'FAILED')"


class ConversationEventRow(AgentBase):
    """Append-only unified conversation timeline event."""

    __tablename__ = "agent_conversation_events"
    __table_args__ = (
        UniqueConstraint(
            "scope_type", "scope_id", "sequence", name="uq_agent_conversation_events_scope_sequence"
        ),
        UniqueConstraint("user_id", "sequence", name="uq_agent_conversation_events_user_sequence"),
        UniqueConstraint("idempotency_key", name="uq_agent_conversation_events_idempotency"),
        Index(
            "ix_agent_conversation_events_scope_time",
            "scope_type",
            "scope_id",
            "occurred_at",
        ),
        CheckConstraint("sequence >= 1", name="ck_agent_conversation_events_sequence"),
        CheckConstraint(_SCOPE_CHECK, name="ck_agent_conversation_events_scope"),
        CheckConstraint(_EVENT_TYPE_CHECK, name="ck_agent_conversation_events_type"),
        CheckConstraint(_ROLE_CHECK, name="ck_agent_conversation_events_role"),
        CheckConstraint(_DELIVERY_CHECK, name="ck_agent_conversation_events_delivery"),
    )

    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    scope_type: Mapped[str] = mapped_column(String(20), nullable=False)
    scope_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    user_id: Mapped[str] = mapped_column(String(120), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_ref: Mapped[str | None] = mapped_column(String(160))
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    delivery_status: Mapped[str | None] = mapped_column(String(16))
    run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    inbox_item_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    notification_intent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    metadata_json: Mapped[dict[str, object]] = mapped_column("metadata", JSONB, nullable=False)


class ConversationSummaryRow(AgentBase):
    """Read-only layered compression view; never replaces original events."""

    __tablename__ = "agent_conversation_summaries"
    __table_args__ = (
        UniqueConstraint(
            "scope_type",
            "scope_id",
            "from_sequence",
            "to_sequence",
            name="uq_agent_conversation_summaries_range",
        ),
        UniqueConstraint("idempotency_key", name="uq_agent_conversation_summaries_idempotency"),
        CheckConstraint(_SCOPE_CHECK, name="ck_agent_conversation_summaries_scope"),
        CheckConstraint(
            "from_sequence >= 1 AND to_sequence >= from_sequence",
            name="ck_agent_conversation_summaries_range",
        ),
        Index(
            "ix_agent_conversation_summaries_scope_to",
            "scope_type",
            "scope_id",
            "to_sequence",
        ),
    )

    summary_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    scope_type: Mapped[str] = mapped_column(String(20), nullable=False)
    scope_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    user_id: Mapped[str] = mapped_column(String(120), nullable=False)
    summary_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    from_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    to_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    structured_json: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
