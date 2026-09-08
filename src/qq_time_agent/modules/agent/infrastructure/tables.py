"""Tables owned by the Agent runtime."""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
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
    execution_epoch: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    context_revision: Mapped[int | None] = mapped_column(Integer)
    context_max_sequence: Mapped[int | None] = mapped_column(Integer)
    context_hash: Mapped[str | None] = mapped_column(String(64))
    __table_args__ = (UniqueConstraint("inbox_item_id", name="uq_agent_runs_inbox_item"),)


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
    metadata_json: Mapped[dict[str, object]] = mapped_column(
        "metadata", JSONB, nullable=False
    )
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
_DELIVERY_CHECK = (
    "delivery_status IS NULL OR delivery_status IN ('DELIVERED', 'FAILED')"
)


class ConversationEventRow(AgentBase):
    """Append-only unified conversation timeline event."""

    __tablename__ = "agent_conversation_events"
    __table_args__ = (
        UniqueConstraint(
            "scope_type", "scope_id", "sequence", name="uq_agent_conversation_events_scope_sequence"
        ),
        UniqueConstraint(
            "user_id", "sequence", name="uq_agent_conversation_events_user_sequence"
        ),
        UniqueConstraint(
            "idempotency_key", name="uq_agent_conversation_events_idempotency"
        ),
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
    metadata_json: Mapped[dict[str, object]] = mapped_column(
        "metadata", JSONB, nullable=False
    )


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
        JSONB, nullable=False, default=dict
    )
    idempotency_key: Mapped[str] = mapped_column(String(240), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
