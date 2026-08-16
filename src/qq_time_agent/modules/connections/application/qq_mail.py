"""QQ Mail password-equivalent credential lifecycle."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from pydantic import SecretStr

from qq_time_agent.contracts.clock import Clock
from qq_time_agent.modules.audit.contracts import AuditEvent, AuditPort
from qq_time_agent.modules.connections.application.cleanup_ports import (
    ConnectionJobCancellationPort,
    ConnectionSourceDeletionPort,
)
from qq_time_agent.modules.connections.application.identity import AccountFingerprinter
from qq_time_agent.modules.connections.application.ports import ConnectionRepository
from qq_time_agent.modules.connections.application.views import to_connection_view
from qq_time_agent.modules.connections.contracts import (
    ConnectionStatusView,
    ConnectionUnavailableError,
    MailAccessGrant,
)
from qq_time_agent.modules.connections.domain.models import (
    ConnectionProvider,
    ConnectionStatus,
    ExternalConnection,
)
from qq_time_agent.modules.credentials.contracts import (
    CredentialKind,
    CredentialRef,
    CredentialVault,
)

QQ_MAIL_CAPABILITIES = frozenset({"Mail.Read"})


class QqMailConnectionVerifier(Protocol):
    async def verify(self, address: str, authorization_code: SecretStr) -> None: ...


@dataclass(frozen=True, slots=True)
class QqMailConnectCommand:
    user_id: str
    address: str
    authorization_code: SecretStr

    def __repr__(self) -> str:
        return (
            "QqMailConnectCommand(user_id=[REDACTED], address=[REDACTED], "
            "authorization_code=[REDACTED])"
        )


class QqMailConnectionService:
    def __init__(
        self,
        repository: ConnectionRepository,
        vault: CredentialVault,
        verifier: QqMailConnectionVerifier,
        jobs: ConnectionJobCancellationPort,
        sources: ConnectionSourceDeletionPort,
        clock: Clock,
        fingerprinter: AccountFingerprinter,
        audit: AuditPort | None = None,
    ) -> None:
        self._repository = repository
        self._vault = vault
        self._verifier = verifier
        self._jobs = jobs
        self._sources = sources
        self._clock = clock
        self._fingerprinter = fingerprinter
        self._audit = audit

    async def connect(self, command: QqMailConnectCommand) -> ConnectionStatusView:
        if command.user_id != "owner":
            raise PermissionError("only the local owner may connect QQ Mail")
        address = _validate_address(command.address)
        fingerprint = self._fingerprinter.fingerprint(ConnectionProvider.QQ_MAIL.value, address)
        connections = await self._repository.list_for_provider(
            command.user_id, ConnectionProvider.QQ_MAIL.value
        )
        existing = next(
            (
                value
                for value in connections
                if value.account_fingerprint == fingerprint or value.provider_account_id == address
            ),
            None,
        )
        if existing is not None and existing.status is ConnectionStatus.ACTIVE:
            raise ValueError("QQ Mail account is already active")
        await self._verifier.verify(address, command.authorization_code)
        credential = await self._vault.store(
            command.authorization_code.get_secret_value(), CredentialKind.IMAP_AUTH_CODE
        )
        connection = existing or ExternalConnection.start(
            command.user_id, ConnectionProvider.QQ_MAIL
        )
        expected_version = connection.version
        if existing is not None:
            connection.restart_authorization()
        connection.bind_identity(
            fingerprint,
            _mask_address(address),
            is_default=(existing is not None and existing.is_default)
            or not _has_default(connections),
        )
        previous = connection.credential_ref
        connection.activate(
            address, _mask_address(address), QQ_MAIL_CAPABILITIES, credential.credential_id
        )
        try:
            await self._sources.allow_connection_sources(connection.connection_id)
            if existing is None:
                await self._repository.add(connection)
            else:
                await self._repository.save(connection, expected_version)
        except Exception:
            await self._sources.block_connection_sources(connection.connection_id)
            await self._vault.delete(credential)
            raise
        if previous is not None:
            await self._vault.delete(CredentialRef(previous))
        await self._audit_event(connection, "connection-activated")
        return to_connection_view(connection)

    async def statuses(self, user_id: str) -> tuple[ConnectionStatusView, ...]:
        values = await self._repository.list_for_provider(user_id, ConnectionProvider.QQ_MAIL.value)
        return tuple(to_connection_view(value) for value in values)

    async def status(self, user_id: str) -> ConnectionStatusView | None:
        values = await self.statuses(user_id)
        return next((value for value in values if value.is_default), values[0] if values else None)

    async def disconnect(self, connection_id: UUID, user_id: str = "owner") -> ConnectionStatusView:
        connection = await self._repository.get_for_user(connection_id, user_id)
        if connection is None or connection.provider is not ConnectionProvider.QQ_MAIL:
            raise LookupError("connection does not exist")
        await self._sources.block_connection_sources(connection_id)
        await self._jobs.cancel_pending_for_connection(connection_id, self._clock.now())
        deleted_reference = connection.credential_ref
        deleted = deleted_reference is None or await self._vault.delete(
            CredentialRef(deleted_reference)
        )
        if not deleted:
            raise RuntimeError("QQ Mail credential deletion failed")
        connection.disconnect(deleted)
        connection = await self._save_disconnected(connection, deleted_reference)
        await self._sources.delete_connection_sources(connection_id)
        await self._audit_event(connection, "connection-disconnected")
        return to_connection_view(connection)

    async def _save_disconnected(
        self, connection: ExternalConnection, deleted_reference: UUID | None
    ) -> ExternalConnection:
        for _ in range(3):
            try:
                await self._repository.save(connection, connection.version - 1)
                return connection
            except RuntimeError:
                connection = await self._require_connection(connection.connection_id)
                if connection.status is ConnectionStatus.DISCONNECTED:
                    return connection
                if (
                    connection.credential_ref is not None
                    and connection.credential_ref != deleted_reference
                ):
                    deleted = await self._vault.delete(CredentialRef(connection.credential_ref))
                    if not deleted:
                        raise RuntimeError("QQ Mail credential deletion failed") from None
                connection.disconnect(True)
        raise RuntimeError("QQ Mail disconnect version conflict")

    async def acquire_mail_access(self, connection_id: UUID) -> MailAccessGrant:
        connection = await self._require_available(connection_id)
        if connection.credential_ref is None or connection.provider_account_id is None:
            raise ValueError("QQ Mail connection has no credential or account")
        handle = await self._vault.open(CredentialRef(connection.credential_ref))
        return MailAccessGrant(
            connection.connection_id, connection.user_id, connection.provider_account_id, handle
        )

    async def ensure_sync_available(self, connection_id: UUID) -> None:
        await self._require_available(connection_id)

    async def mark_sync_succeeded(self, connection_id: UUID, completed_at: datetime) -> None:
        if completed_at.tzinfo is None or completed_at.utcoffset() is None:
            raise ValueError("sync completion time must be timezone-aware")
        connection = await self._require_available(connection_id)
        connection.last_synced_at = completed_at
        connection.status = ConnectionStatus.ACTIVE
        connection.reauth_required_since = None
        connection.version += 1
        await self._repository.save(connection, connection.version - 1)

    async def mark_sync_reauth_required(self, connection_id: UUID) -> None:
        connection = await self._require_connection(connection_id)
        connection.require_reauthorization(self._clock.now())
        await self._repository.save(connection, connection.version - 1)

    async def mark_sync_degraded(self, connection_id: UUID) -> None:
        connection = await self._require_available(connection_id)
        connection.mark_degraded()
        await self._repository.save(connection, connection.version - 1)

    async def _require_connection(self, connection_id: UUID) -> ExternalConnection:
        connection = await self._repository.get(connection_id)
        if connection is None:
            raise LookupError("connection does not exist")
        return connection

    async def _require_available(self, connection_id: UUID) -> ExternalConnection:
        connection = await self._require_connection(connection_id)
        if (
            connection.provider is not ConnectionProvider.QQ_MAIL
            or not connection.sync_enabled
            or connection.status not in {ConnectionStatus.ACTIVE, ConnectionStatus.DEGRADED}
        ):
            raise ConnectionUnavailableError("QQ Mail connection is not available")
        return connection

    async def _audit_event(self, connection: ExternalConnection, event_type: str) -> None:
        if self._audit is not None:
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


def _validate_address(value: str) -> str:
    normalized = value.strip().lower()
    if len(normalized) > 320 or "@" not in normalized or not normalized.endswith("@qq.com"):
        raise ValueError("a complete QQ Mail address is required")
    return normalized


def _mask_address(value: str) -> str:
    local, domain = value.split("@", 1)
    return f"{local[:1]}***@{domain}"


def _has_default(values: tuple[ExternalConnection, ...]) -> bool:
    return any(
        value.is_default and value.status is not ConnectionStatus.DISCONNECTED for value in values
    )
