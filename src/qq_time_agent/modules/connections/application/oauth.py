"""Delegated Microsoft OAuth lifecycle with one-time state and encrypted flow storage."""

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from qq_time_agent.contracts.clock import Clock
from qq_time_agent.modules.audit.contracts import AuditEvent, AuditPort
from qq_time_agent.modules.connections.application.ports import (
    ConnectionRepository,
    MicrosoftConnectionProvider,
    OAuthProviderError,
)
from qq_time_agent.modules.connections.contracts import (
    ConnectionStatusView,
    ConnectionUnavailableError,
    MailAccessGrant,
)
from qq_time_agent.modules.connections.domain.models import (
    ConnectionProvider,
    ConnectionStatus,
    ExternalConnection,
    OAuthTransaction,
)
from qq_time_agent.modules.credentials.contracts import (
    CredentialHandle,
    CredentialKind,
    CredentialRef,
    CredentialVault,
)

CONNECTION_CAPABILITIES = frozenset({"User.Read", "Mail.Read"})


@dataclass(frozen=True, slots=True)
class AuthorizationStart:
    authorization_url: str
    browser_session: str


class OAuthSecurityError(RuntimeError):
    pass


class MicrosoftConnectionService:
    def __init__(
        self,
        repository: ConnectionRepository,
        vault: CredentialVault,
        provider: MicrosoftConnectionProvider,
        clock: Clock,
        transaction_ttl: timedelta = timedelta(minutes=10),
        audit: AuditPort | None = None,
    ) -> None:
        self._repository = repository
        self._vault = vault
        self._provider = provider
        self._clock = clock
        self._transaction_ttl = transaction_ttl
        self._audit = audit

    async def begin(self, user_id: str) -> AuthorizationStart:
        existing = await self._repository.get_for_provider(
            user_id, ConnectionProvider.MICROSOFT.value
        )
        if existing is not None and existing.status is ConnectionStatus.ACTIVE:
            raise ValueError("Microsoft connection is already active")
        now = self._clock.now()
        state = secrets.token_urlsafe(32)
        browser_session = secrets.token_urlsafe(32)
        authorization = await self._provider.begin_authorization(state)
        expires_at = now + self._transaction_ttl
        flow_ref = await self._vault.store(
            authorization.flow_state.get_secret_value(), CredentialKind.OAUTH_FLOW, expires_at
        )
        connection = existing or ExternalConnection.start(user_id, ConnectionProvider.MICROSOFT)
        if existing is not None:
            connection.restart_authorization()
        transaction = OAuthTransaction(
            uuid4(),
            connection.connection_id,
            user_id,
            _hash(state),
            _hash(browser_session),
            flow_ref.credential_id,
            expires_at,
            now,
        )
        try:
            await self._repository.add_authorization(connection, transaction)
        except Exception:
            await self._vault.delete(flow_ref)
            raise
        return AuthorizationStart(authorization.authorization_url, browser_session)

    async def complete(
        self, callback_parameters: dict[str, str], browser_session: str
    ) -> ConnectionStatusView:
        state = callback_parameters.get("state", "")
        if not state or not browser_session:
            raise OAuthSecurityError("OAuth state and browser session are required")
        transaction = await self._repository.claim_transaction(
            _hash(state), _hash(browser_session), self._clock.now()
        )
        if transaction is None:
            raise OAuthSecurityError("OAuth transaction is invalid, expired, or already used")
        flow_ref = CredentialRef(transaction.flow_credential_ref)
        try:
            return await self._exchange_and_activate(transaction, flow_ref, callback_parameters)
        finally:
            await self._vault.delete(flow_ref)

    async def refresh(self, connection_id: UUID) -> ConnectionStatusView:
        connection = await self._require_connection(connection_id)
        if connection.credential_ref is None:
            raise ValueError("connection has no refresh credential")
        reference = CredentialRef(connection.credential_ref)
        handle = await self._vault.open(reference)
        try:
            tokens = await self._provider.refresh(handle.reveal(self._clock.now()))
            profile = await self._provider.get_profile(tokens.access_token.get_secret_value())
        except OAuthProviderError as exc:
            if exc.failure_class == "Authentication":
                await self._mark_reauthorization(connection)
            raise
        if tokens.refresh_token is not None:
            await self._vault.replace(reference, tokens.refresh_token.get_secret_value())
        connection.activate(
            profile.account_id,
            _mask_account(profile.email),
            CONNECTION_CAPABILITIES,
            reference.credential_id,
        )
        await self._save(connection)
        return _view(connection)

    async def disconnect(self, connection_id: UUID) -> ConnectionStatusView:
        connection = await self._require_connection(connection_id)
        deleted = True
        if connection.credential_ref is not None:
            deleted = await self._vault.delete(CredentialRef(connection.credential_ref))
        connection.disconnect(deleted)
        await self._save(connection)
        await self._audit_connection(connection, "connection-disconnected")
        return _view(connection)

    async def status(self, user_id: str) -> ConnectionStatusView | None:
        connection = await self._repository.get_for_provider(
            user_id, ConnectionProvider.MICROSOFT.value
        )
        return None if connection is None else _view(connection)

    async def acquire_mail_access(self, connection_id: UUID) -> MailAccessGrant:
        connection = await self._require_connection(connection_id)
        if connection.status not in {ConnectionStatus.ACTIVE, ConnectionStatus.DEGRADED}:
            raise ConnectionUnavailableError("connection is not available for mail synchronization")
        if connection.credential_ref is None:
            raise ValueError("connection has no refresh credential")
        reference = CredentialRef(connection.credential_ref)
        refresh_handle = await self._vault.open(reference)
        try:
            tokens = await self._provider.refresh(refresh_handle.reveal(self._clock.now()))
        except OAuthProviderError as exc:
            if exc.failure_class == "Authentication":
                await self._mark_reauthorization(connection)
            elif exc.failure_class in {"TransientProvider", "RateLimit"}:
                connection.mark_degraded()
                await self._save(connection)
            raise
        if tokens.refresh_token is not None:
            await self._vault.replace(reference, tokens.refresh_token.get_secret_value())
        handle = CredentialHandle(
            tokens.access_token.get_secret_value(), CredentialKind.ACCESS_TOKEN, tokens.expires_at
        )
        if connection.provider_account_id is None:
            raise ValueError("connection has no provider account")
        return MailAccessGrant(
            connection.connection_id,
            connection.user_id,
            connection.provider_account_id,
            handle,
        )

    async def ensure_sync_available(self, connection_id: UUID) -> None:
        connection = await self._require_connection(connection_id)
        if connection.status not in {ConnectionStatus.ACTIVE, ConnectionStatus.DEGRADED}:
            raise ConnectionUnavailableError("connection is not available for mail synchronization")

    async def mark_sync_succeeded(self, connection_id: UUID, completed_at: datetime) -> None:
        connection = await self._require_connection(connection_id)
        if completed_at.tzinfo is None or completed_at.utcoffset() is None:
            raise ValueError("sync completion time must be timezone-aware")
        connection.last_synced_at = completed_at
        connection.status = ConnectionStatus.ACTIVE
        connection.version += 1
        await self._save(connection)

    async def mark_sync_reauth_required(self, connection_id: UUID) -> None:
        connection = await self._require_connection(connection_id)
        await self._mark_reauthorization(connection)

    async def mark_sync_degraded(self, connection_id: UUID) -> None:
        connection = await self._require_connection(connection_id)
        connection.mark_degraded()
        await self._save(connection)

    async def _exchange_and_activate(
        self,
        transaction: OAuthTransaction,
        flow_ref: CredentialRef,
        callback_parameters: dict[str, str],
    ) -> ConnectionStatusView:
        flow = await self._vault.open(flow_ref)
        tokens = await self._provider.complete_authorization(
            flow.reveal(self._clock.now()), _safe_callback(callback_parameters)
        )
        if tokens.refresh_token is None:
            raise OAuthProviderError("Authentication")
        profile = await self._provider.get_profile(tokens.access_token.get_secret_value())
        refresh_ref = await self._vault.store(
            tokens.refresh_token.get_secret_value(), CredentialKind.REFRESH_TOKEN
        )
        connection = await self._require_connection(transaction.connection_id)
        connection.activate(
            profile.account_id,
            _mask_account(profile.email),
            CONNECTION_CAPABILITIES,
            refresh_ref.credential_id,
        )
        try:
            await self._save(connection)
        except Exception:
            await self._vault.delete(refresh_ref)
            raise
        await self._audit_connection(connection, "connection-activated")
        return _view(connection)

    async def _require_connection(self, connection_id: UUID) -> ExternalConnection:
        connection = await self._repository.get(connection_id)
        if connection is None:
            raise LookupError("connection does not exist")
        return connection

    async def _save(self, connection: ExternalConnection) -> None:
        await self._repository.save(connection, connection.version - 1)

    async def _mark_reauthorization(self, connection: ExternalConnection) -> None:
        connection.require_reauthorization()
        await self._save(connection)

    async def _audit_connection(self, connection: ExternalConnection, event_type: str) -> None:
        if self._audit is None:
            return
        await self._audit.append(
            AuditEvent(
                event_type,
                connection.user_id,
                f"connection:{connection.connection_id}",
                connection.status.value,
                self._clock.now(),
                {"provider": connection.provider.value},
            )
        )


def _hash(value: str) -> bytes:
    return hashlib.sha256(value.encode()).digest()


def _mask_account(email: str | None) -> str:
    if not email or "@" not in email:
        return "account"
    local, domain = email.split("@", 1)
    return f"{local[:1]}***@{domain}"


def _safe_callback(parameters: dict[str, str]) -> dict[str, str]:
    allowed = {"code", "state", "error", "error_description", "error_uri"}
    return {key: value for key, value in parameters.items() if key in allowed}


def _view(connection: ExternalConnection) -> ConnectionStatusView:
    return ConnectionStatusView(
        connection.connection_id,
        connection.provider.value,
        connection.status.value,
        tuple(sorted(connection.capabilities)),
        connection.account_mask,
        connection.last_synced_at,
    )
