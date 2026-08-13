"""SQLAlchemy tables owned exclusively by Connections."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, LargeBinary, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class ConnectionsBase(DeclarativeBase):
    pass


class ConnectionRow(ConnectionsBase):
    __tablename__ = "connections_external_connections"

    connection_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(120), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    provider_account_id: Mapped[str | None] = mapped_column(String(200))
    account_mask: Mapped[str | None] = mapped_column(String(240))
    capabilities: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    credential_ref: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (UniqueConstraint("user_id", "provider", name="uq_connections_user_provider"),)


class OAuthTransactionRow(ConnectionsBase):
    __tablename__ = "connections_oauth_transactions"

    transaction_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    connection_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    user_id: Mapped[str] = mapped_column(String(120), nullable=False)
    state_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False, unique=True)
    browser_session_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    flow_credential_ref: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_connections_oauth_claim", "state_hash", "expires_at", "consumed_at"),
    )
