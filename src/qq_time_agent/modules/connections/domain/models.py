"""Pure state machines for delegated external connections and OAuth transactions."""

import secrets
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4


class ConnectionProvider(StrEnum):
    MICROSOFT = "MICROSOFT"
    QQ_MAIL = "QQ_MAIL"


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
    account_fingerprint: str | None = None
    display_label: str = "Mailbox"
    is_default: bool = True
    sync_enabled: bool = True
    reauth_epoch: int = 0
    reauth_required_since: datetime | None = None

    @classmethod
    def start(cls, user_id: str, provider: ConnectionProvider) -> "ExternalConnection":
        if not user_id.strip():
            raise ValueError("user_id is required")
        return cls(
            uuid4(),
            user_id,
            provider,
            ConnectionStatus.PENDING,
            display_label=provider.value.replace("_", " ").title(),
        )

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
        self.sync_enabled = True
        self.reauth_required_since = None
        self.version += 1

    def require_reauthorization(self, now: datetime) -> None:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("reauthorization time must be timezone-aware")
        if self.status is ConnectionStatus.DISCONNECTED:
            return
        if self.status is not ConnectionStatus.REAUTH_REQUIRED:
            self.reauth_epoch += 1
            self.reauth_required_since = now
        self.status = ConnectionStatus.REAUTH_REQUIRED
        self.version += 1

    def mark_degraded(self) -> None:
        if self.status in {ConnectionStatus.ACTIVE, ConnectionStatus.DEGRADED}:
            self.status = ConnectionStatus.DEGRADED
            self.version += 1

    def restart_authorization(self) -> None:
        if self.status is ConnectionStatus.ACTIVE:
            raise ValueError("active connection cannot restart authorization")
        self.status = ConnectionStatus.PENDING
        self.reauth_required_since = None
        self.version += 1

    def bind_identity(self, fingerprint: str, display_label: str, *, is_default: bool) -> None:
        if not fingerprint.strip() or len(fingerprint) > 80:
            raise ValueError("account fingerprint must be non-empty and bounded")
        if not display_label.strip() or len(display_label) > 120:
            raise ValueError("connection display label must be non-empty and bounded")
        if (
            self.account_fingerprint is not None
            and not self.account_fingerprint.startswith("legacy:")
            and self.account_fingerprint != fingerprint
        ):
            raise ValueError("connection identity cannot change")
        self.account_fingerprint = fingerprint
        self.display_label = display_label
        self.is_default = is_default

    def set_sync_enabled(self, enabled: bool) -> None:
        if self.status is ConnectionStatus.DISCONNECTED and enabled:
            raise ValueError("disconnected connection cannot enable synchronization")
        if self.sync_enabled != enabled:
            self.sync_enabled = enabled
            self.version += 1

    def disconnect(self, credential_deleted: bool) -> None:
        if not credential_deleted and self.credential_ref is not None:
            raise ValueError("credential must be deleted before disconnect")
        self.credential_ref = None
        self.status = ConnectionStatus.DISCONNECTED
        self.reauth_required_since = None
        self.sync_enabled = False
        self.is_default = False
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
