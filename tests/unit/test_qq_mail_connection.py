from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import SecretStr

from qq_time_agent.modules.connections.application.qq_mail import (
    QqMailConnectCommand,
    QqMailConnectionService,
)
from qq_time_agent.modules.connections.contracts import ConnectionUnavailableError
from qq_time_agent.modules.connections.domain.models import ExternalConnection
from qq_time_agent.modules.connections.infrastructure.fingerprints import HmacAccountFingerprinter
from qq_time_agent.modules.credentials.contracts import (
    CredentialHandle,
    CredentialKind,
    CredentialRef,
)


@dataclass
class Clock:
    def now(self) -> datetime:
        return datetime(2026, 8, 13, tzinfo=UTC)


@dataclass
class Repository:
    values: dict[UUID, ExternalConnection] = field(default_factory=dict)

    async def add(self, connection: ExternalConnection) -> None:
        self.values[connection.connection_id] = connection

    async def add_authorization(self, connection: object, transaction: object) -> None:
        raise AssertionError

    async def claim_transaction(
        self, state_hash: bytes, browser_hash: bytes, now: datetime
    ) -> None:
        raise AssertionError

    async def get(self, connection_id: UUID) -> ExternalConnection | None:
        return self.values.get(connection_id)

    async def get_for_provider(self, user_id: str, provider: str) -> ExternalConnection | None:
        return next(
            (
                value
                for value in self.values.values()
                if value.user_id == user_id and value.provider.value == provider
            ),
            None,
        )

    async def list_for_provider(
        self, user_id: str, provider: str
    ) -> tuple[ExternalConnection, ...]:
        return tuple(
            value
            for value in self.values.values()
            if value.user_id == user_id and value.provider.value == provider
        )

    async def get_for_user(self, connection_id: UUID, user_id: str) -> ExternalConnection | None:
        value = self.values.get(connection_id)
        return value if value is not None and value.user_id == user_id else None

    async def get_by_identity(
        self, user_id: str, provider: str, fingerprint: str
    ) -> ExternalConnection | None:
        return next(
            (
                value
                for value in self.values.values()
                if value.user_id == user_id
                and value.provider.value == provider
                and value.account_fingerprint == fingerprint
            ),
            None,
        )

    async def save(self, connection: ExternalConnection, expected_version: int) -> None:
        assert self.values[connection.connection_id].version >= expected_version
        self.values[connection.connection_id] = connection


@dataclass
class Vault:
    values: dict[UUID, str] = field(default_factory=dict)

    async def store(
        self, material: str, kind: CredentialKind, expires_at: datetime | None = None
    ) -> CredentialRef:
        from uuid import uuid4

        assert kind is CredentialKind.IMAP_AUTH_CODE
        reference = CredentialRef(uuid4())
        self.values[reference.credential_id] = material
        return reference

    async def open(self, reference: CredentialRef) -> CredentialHandle:
        return CredentialHandle(
            self.values[reference.credential_id], CredentialKind.IMAP_AUTH_CODE, None
        )

    async def replace(self, reference: CredentialRef, material: str) -> None:
        self.values[reference.credential_id] = material

    async def delete(self, reference: CredentialRef) -> bool:
        return self.values.pop(reference.credential_id, None) is not None


@dataclass
class Verifier:
    codes: list[str] = field(default_factory=list)

    async def verify(self, address: str, authorization_code: SecretStr) -> None:
        assert address.endswith("@qq.com")
        self.codes.append(authorization_code.get_secret_value())


@dataclass
class Jobs:
    cancelled: list[UUID] = field(default_factory=list)

    async def cancel_pending_for_connection(
        self, connection_id: UUID, cancelled_at: datetime
    ) -> int:
        assert cancelled_at.tzinfo is not None
        self.cancelled.append(connection_id)
        return 1


@dataclass
class Sources:
    deleted: list[UUID] = field(default_factory=list)
    blocked: list[UUID] = field(default_factory=list)
    allowed: list[UUID] = field(default_factory=list)

    async def delete_connection_sources(self, connection_id: UUID) -> int:
        self.deleted.append(connection_id)
        return 2

    async def allow_connection_sources(self, connection_id: UUID) -> None:
        self.allowed.append(connection_id)

    async def block_connection_sources(self, connection_id: UUID) -> None:
        self.blocked.append(connection_id)


def service() -> tuple[QqMailConnectionService, Repository, Vault, Verifier, Jobs, Sources]:
    repository, vault, verifier, jobs, sources = (
        Repository(),
        Vault(),
        Verifier(),
        Jobs(),
        Sources(),
    )
    value = QqMailConnectionService(
        repository,
        vault,
        verifier,
        jobs,
        sources,
        Clock(),
        HmacAccountFingerprinter(SecretStr("test-fingerprint-key")),
    )
    return value, repository, vault, verifier, jobs, sources


@pytest.mark.asyncio
async def test_connect_stores_only_reference_and_redacts_command() -> None:
    value, repository, vault, verifier, _, _ = service()
    code = "not-for-logs-authorization-code"
    command = QqMailConnectCommand("owner", "Owner@QQ.COM", SecretStr(code))
    view = await value.connect(command)

    connection = repository.values[view.connection_id]
    assert view.status == "ACTIVE" and connection.credential_ref is not None
    assert code not in repr(command) and code not in repr(connection)
    assert verifier.codes == [code] and list(vault.values.values()) == [code]


@pytest.mark.asyncio
async def test_non_owner_is_rejected_before_verification_or_storage() -> None:
    value, _, vault, verifier, _, _ = service()
    with pytest.raises(PermissionError):
        await value.connect(
            QqMailConnectCommand("intruder", "owner@qq.com", SecretStr("synthetic-code"))
        )
    assert not verifier.codes and not vault.values


@pytest.mark.asyncio
async def test_disconnect_cancels_jobs_deletes_sources_and_credential() -> None:
    value, repository, vault, _, jobs, sources = service()
    connected = await value.connect(
        QqMailConnectCommand("owner", "owner@qq.com", SecretStr("synthetic-code"))
    )
    result = await value.disconnect(connected.connection_id)

    assert result.status == "DISCONNECTED"
    assert not vault.values
    assert jobs.cancelled == [connected.connection_id]
    assert sources.deleted == [connected.connection_id]
    assert sources.blocked == [connected.connection_id]
    assert repository.values[connected.connection_id].credential_ref is None


@pytest.mark.asyncio
async def test_reauthentication_replaces_old_credential() -> None:
    value, repository, vault, _, _, _ = service()
    initial = await value.connect(
        QqMailConnectCommand("owner", "owner@qq.com", SecretStr("synthetic-old"))
    )
    connection = repository.values[initial.connection_id]
    connection.require_reauthorization(datetime(2026, 8, 13, tzinfo=UTC))
    replacement = await value.connect(
        QqMailConnectCommand("owner", "owner@qq.com", SecretStr("synthetic-new"))
    )
    assert replacement.connection_id == initial.connection_id
    assert list(vault.values.values()) == ["synthetic-new"]


@pytest.mark.asyncio
async def test_authentication_failure_moves_connection_to_reauth_required() -> None:
    value, _, _, _, _, _ = service()
    connected = await value.connect(
        QqMailConnectCommand("owner", "owner@qq.com", SecretStr("synthetic-code"))
    )
    await value.mark_sync_reauth_required(connected.connection_id)
    status = await value.status("owner")
    assert status is not None and status.status == "REAUTH_REQUIRED"
    with pytest.raises(ConnectionUnavailableError, match="not available"):
        await value.acquire_mail_access(connected.connection_id)


@pytest.mark.asyncio
async def test_sync_success_records_timezone_aware_completion() -> None:
    value, _, _, _, _, _ = service()
    connected = await value.connect(
        QqMailConnectCommand("owner", "owner@qq.com", SecretStr("synthetic-code"))
    )
    await value.mark_sync_succeeded(connected.connection_id, Clock().now())
    status = await value.status("owner")
    assert status is not None and status.last_synced_at == Clock().now()
    with pytest.raises(ValueError, match="timezone-aware"):
        await value.mark_sync_succeeded(connected.connection_id, datetime(2026, 8, 13))


@pytest.mark.asyncio
async def test_transient_failure_degrades_and_success_recovers_connection() -> None:
    value, _, _, _, _, _ = service()
    connected = await value.connect(
        QqMailConnectCommand("owner", "owner@qq.com", SecretStr("synthetic-code"))
    )
    await value.mark_sync_degraded(connected.connection_id)
    degraded = await value.status("owner")
    assert degraded is not None and degraded.status == "DEGRADED"
    await value.mark_sync_succeeded(connected.connection_id, Clock().now())
    recovered = await value.status("owner")
    assert recovered is not None and recovered.status == "ACTIVE"


@pytest.mark.asyncio
async def test_connect_supports_multiple_qq_mail_accounts() -> None:
    value, repository, _, _, _, _ = service()
    first = await value.connect(
        QqMailConnectCommand("owner", "first@qq.com", SecretStr("first-code"))
    )
    second = await value.connect(
        QqMailConnectCommand("owner", "second@qq.com", SecretStr("second-code"))
    )
    statuses = await value.statuses("owner")
    assert {status.connection_id for status in statuses} == {
        first.connection_id,
        second.connection_id,
    }
    assert sum(status.is_default for status in statuses) == 1
    assert len(repository.values) == 2
