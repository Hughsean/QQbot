"""Pure state machines for delegated external connections and OAuth transactions."""

import secrets
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4


class ConnectionProvider(StrEnum):
    MICROSOFT = "MICROSOFT"


class ConnectionStatus(StrEnum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    DEGRADED = "DEGRADED"
    REAUTH_REQUIRED = "REAUTH_REQUIRED"
    DISCONNECTED = "DISCONNECTED"


@dataclass(slots=True)
class ExternalConnection:
    connection_id: UUID
    user_id: str
    provider: ConnectionProvider
    status: ConnectionStatus
    provider_account_id: str | None = None
    account_mask: str | None = None
    capabilities: frozenset[str] = frozenset()
    credential_ref: UUID | None = None
    last_synced_at: datetime | None = None
    version: int = 1

    @classmethod
    def start(cls, user_id: str, provider: ConnectionProvider) -> "ExternalConnection":
        if not user_id.strip():
            raise ValueError("user_id is required")
        return cls(uuid4(), user_id, provider, ConnectionStatus.PENDING)

    def activate(
        self,
        provider_account_id: str,
        account_mask: str,
        capabilities: frozenset[str],
        credential_ref: UUID,
    ) -> None:
        if self.status is ConnectionStatus.DISCONNECTED:
            raise ValueError("disconnected connection cannot be activated")
        if not provider_account_id or not capabilities:
            raise ValueError("provider account and capabilities are required")
        self.provider_account_id = provider_account_id
        self.account_mask = account_mask
        self.capabilities = capabilities
        self.credential_ref = credential_ref
        self.status = ConnectionStatus.ACTIVE
        self.version += 1

    def require_reauthorization(self) -> None:
        if self.status is not ConnectionStatus.DISCONNECTED:
            self.status = ConnectionStatus.REAUTH_REQUIRED
            self.version += 1

    def restart_authorization(self) -> None:
        if self.status is ConnectionStatus.ACTIVE:
            raise ValueError("active connection cannot restart authorization")
        self.status = ConnectionStatus.PENDING
        self.version += 1

    def disconnect(self, credential_deleted: bool) -> None:
        if not credential_deleted and self.credential_ref is not None:
            raise ValueError("credential must be deleted before disconnect")
        self.credential_ref = None
        self.status = ConnectionStatus.DISCONNECTED
        self.version += 1


@dataclass(slots=True)
class OAuthTransaction:
    transaction_id: UUID
    connection_id: UUID
    user_id: str
    state_hash: bytes
    browser_session_hash: bytes
    flow_credential_ref: UUID
    expires_at: datetime
    created_at: datetime
    consumed_at: datetime | None = None

    def claim(self, state_hash: bytes, browser_session_hash: bytes, now: datetime) -> None:
        _require_aware(now)
        if self.consumed_at is not None:
            raise ValueError("OAuth transaction was already consumed")
        if now >= self.expires_at:
            raise ValueError("OAuth transaction has expired")
        if not secrets.compare_digest(self.state_hash, state_hash):
            raise ValueError("OAuth state mismatch")
        if not secrets.compare_digest(self.browser_session_hash, browser_session_hash):
            raise ValueError("OAuth browser session mismatch")
        self.consumed_at = now


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timezone-aware datetime required")
