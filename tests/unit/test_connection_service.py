import base64
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse
from uuid import UUID

import pytest
from pydantic import SecretStr

from qq_time_agent.modules.connections.application.oauth import (
    MicrosoftConnectionService,
    OAuthSecurityError,
)
from qq_time_agent.modules.connections.application.ports import (
    OAuthProviderError,
    ProviderAuthorization,
    ProviderProfile,
    ProviderTokens,
)
from qq_time_agent.modules.connections.contracts import (
    ConnectionStatusView,
    ConnectionUnavailableError,
)
from qq_time_agent.modules.connections.domain.models import ExternalConnection, OAuthTransaction
from qq_time_agent.modules.credentials.application.ports import EncryptedCredential
from qq_time_agent.modules.credentials.application.vault import VaultService
from qq_time_agent.modules.credentials.infrastructure.cipher import AesGcmCredentialCipher


@dataclass
class FixedClock:
    value: datetime

    def now(self) -> datetime:
        return self.value


@dataclass
class MemoryCredentialRepository:
    records: dict[UUID, EncryptedCredential] = field(default_factory=dict)

    async def add(self, credential: EncryptedCredential) -> None:
        self.records[credential.credential_id] = credential

    async def get(self, credential_id: UUID) -> EncryptedCredential | None:
        return self.records.get(credential_id)

    async def replace(self, credential: EncryptedCredential) -> bool:
        if credential.credential_id not in self.records:
            return False
        self.records[credential.credential_id] = credential
        return True

    async def delete(self, credential_id: UUID) -> bool:
        return self.records.pop(credential_id, None) is not None


@dataclass
class MemoryConnectionRepository:
    connections: dict[UUID, ExternalConnection] = field(default_factory=dict)
    transactions: list[OAuthTransaction] = field(default_factory=list)
    fail_add: bool = False
    fail_save: bool = False

    async def add(self, connection: ExternalConnection) -> None:
        self.connections[connection.connection_id] = connection

    async def add_authorization(
        self, connection: ExternalConnection, transaction: OAuthTransaction
    ) -> None:
        if self.fail_add:
            raise RuntimeError("synthetic add failure")
        self.connections[connection.connection_id] = connection
        self.transactions.append(transaction)

    async def claim_transaction(
        self, state_hash: bytes, browser_hash: bytes, now: datetime
    ) -> OAuthTransaction | None:
        for transaction in self.transactions:
            try:
                transaction.claim(state_hash, browser_hash, now)
            except ValueError:
                continue
            return transaction
        return None

    async def get(self, connection_id: UUID) -> ExternalConnection | None:
        return self.connections.get(connection_id)

    async def get_for_provider(self, user_id: str, provider: str) -> ExternalConnection | None:
        return next(
            (
                item
                for item in self.connections.values()
                if item.user_id == user_id and item.provider.value == provider
            ),
            None,
        )

    async def save(self, connection: ExternalConnection, expected_version: int) -> None:
        if self.fail_save:
            raise RuntimeError("synthetic save failure")
        current = self.connections.get(connection.connection_id)
        if current is None or connection.version != expected_version + 1:
            raise RuntimeError("version conflict")
        self.connections[connection.connection_id] = connection


@dataclass
class FakeMicrosoftProvider:
    refresh_calls: list[str] = field(default_factory=list)
    refresh_failure_class: str | None = None
    completion_refresh_token: str | None = "refresh-one"
    rotated_refresh_token: str | None = "refresh-two"
    profile_email: str | None = "owner@example.test"

    async def begin_authorization(self, state: str) -> ProviderAuthorization:
        return ProviderAuthorization(
            f"https://login.example.test/authorize?state={state}", SecretStr("encrypted-flow-input")
        )

    async def complete_authorization(
        self, flow_state: str, callback_parameters: dict[str, str]
    ) -> ProviderTokens:
        assert flow_state == "encrypted-flow-input"
        assert callback_parameters["code"] == "synthetic-code"
        return ProviderTokens(
            SecretStr("access-one"),
            (
                SecretStr(self.completion_refresh_token)
                if self.completion_refresh_token is not None
                else None
            ),
            datetime(2026, 8, 13, 1, tzinfo=UTC),
        )

    async def refresh(self, refresh_token: str) -> ProviderTokens:
        self.refresh_calls.append(refresh_token)
        if self.refresh_failure_class is not None:
            raise OAuthProviderError(self.refresh_failure_class)
        return ProviderTokens(
            SecretStr("access-two"),
            (
                SecretStr(self.rotated_refresh_token)
                if self.rotated_refresh_token is not None
                else None
            ),
            datetime(2026, 8, 13, 2, tzinfo=UTC),
        )

    async def get_profile(self, access_token: str) -> ProviderProfile:
        return ProviderProfile("account-id", "Owner", self.profile_email)


def _service() -> tuple[
    MicrosoftConnectionService,
    MemoryConnectionRepository,
    MemoryCredentialRepository,
    FakeMicrosoftProvider,
    FixedClock,
]:
    clock = FixedClock(datetime(2026, 8, 13, tzinfo=UTC))
    credentials = MemoryCredentialRepository()
    key = base64.urlsafe_b64encode(b"k" * 32).decode()
    vault = VaultService(credentials, AesGcmCredentialCipher(SecretStr(key)), clock)
    connections = MemoryConnectionRepository()
    provider = FakeMicrosoftProvider()
    return (
        MicrosoftConnectionService(connections, vault, provider, clock),
        connections,
        credentials,
        provider,
        clock,
    )


@pytest.mark.asyncio
async def test_authorization_activation_refresh_rotation_and_disconnect() -> None:
    service, connections, credentials, provider, _ = _service()
    start = await service.begin("owner")
    state = parse_qs(urlparse(start.authorization_url).query)["state"][0]
    view = await service.complete(
        {"state": state, "code": "synthetic-code", "ignored": "provider-dto"},
        start.browser_session,
    )
    assert view.status == "ACTIVE"
    assert view.account_mask == "o***@example.test"
    assert view.capabilities == ("Mail.Read", "User.Read")
    assert len(credentials.records) == 1
    assert all(b"refresh-one" not in item.ciphertext for item in credentials.records.values())

    refreshed = await service.refresh(view.connection_id)
    assert refreshed.status == "ACTIVE"
    assert provider.refresh_calls == ["refresh-one"]
    assert len(credentials.records) == 1
    disconnected = await service.disconnect(view.connection_id)
    assert disconnected.status == "DISCONNECTED"
    assert credentials.records == {}
    assert connections.connections[view.connection_id].credential_ref is None


@pytest.mark.asyncio
async def test_oauth_callback_is_one_time_and_browser_bound() -> None:
    service, _, _, _, _ = _service()
    start = await service.begin("owner")
    state = parse_qs(urlparse(start.authorization_url).query)["state"][0]
    with pytest.raises(OAuthSecurityError):
        await service.complete({"state": state, "code": "synthetic-code"}, "wrong-browser")
    await service.complete({"state": state, "code": "synthetic-code"}, start.browser_session)
    with pytest.raises(OAuthSecurityError):
        await service.complete({"state": state, "code": "synthetic-code"}, start.browser_session)


@pytest.mark.asyncio
async def test_refresh_authentication_failure_enters_reauth_required() -> None:
    service, connections, _, provider, _ = _service()
    start = await service.begin("owner")
    state = parse_qs(urlparse(start.authorization_url).query)["state"][0]
    view = await service.complete({"state": state, "code": "synthetic-code"}, start.browser_session)
    provider.refresh_failure_class = "Authentication"
    with pytest.raises(OAuthProviderError, match="Authentication"):
        await service.refresh(view.connection_id)
    assert connections.connections[view.connection_id].status.value == "REAUTH_REQUIRED"


@pytest.mark.asyncio
async def test_begin_rejects_active_connection_and_cleans_failed_transaction() -> None:
    service, _, _, _, _ = _service()
    start = await service.begin("owner")
    state = parse_qs(urlparse(start.authorization_url).query)["state"][0]
    await service.complete({"state": state, "code": "synthetic-code"}, start.browser_session)
    with pytest.raises(ValueError, match="already active"):
        await service.begin("owner")

    failed_service, failed_connections, failed_credentials, _, _ = _service()
    failed_connections.fail_add = True
    with pytest.raises(RuntimeError, match="synthetic add failure"):
        await failed_service.begin("owner")
    assert failed_credentials.records == {}


@pytest.mark.asyncio
async def test_reauthorization_begin_and_missing_callback_context() -> None:
    service, connections, _, _, _ = _service()
    first = await service.begin("owner")
    connection = next(iter(connections.connections.values()))
    connection.require_reauthorization()
    second = await service.begin("owner")
    assert first.browser_session != second.browser_session
    assert connection.status.value == "PENDING"
    with pytest.raises(OAuthSecurityError, match="required"):
        await service.complete({}, second.browser_session)
    with pytest.raises(OAuthSecurityError, match="required"):
        await service.complete({"state": "state"}, "")


@pytest.mark.asyncio
async def test_completion_requires_refresh_token_and_cleans_failed_save() -> None:
    service, _, credentials, provider, _ = _service()
    start = await service.begin("owner")
    state = parse_qs(urlparse(start.authorization_url).query)["state"][0]
    provider.completion_refresh_token = None
    with pytest.raises(OAuthProviderError, match="Authentication"):
        await service.complete({"state": state, "code": "synthetic-code"}, start.browser_session)
    assert credentials.records == {}

    service, connections, credentials, _, _ = _service()
    start = await service.begin("owner")
    state = parse_qs(urlparse(start.authorization_url).query)["state"][0]
    connections.fail_save = True
    with pytest.raises(RuntimeError, match="synthetic save failure"):
        await service.complete({"state": state, "code": "synthetic-code"}, start.browser_session)
    assert credentials.records == {}


@pytest.mark.asyncio
async def test_status_pending_disconnect_and_refresh_error_branches() -> None:
    service, _, _, _, _ = _service()
    assert await service.status("owner") is None
    start = await service.begin("owner")
    pending = await service.status("owner")
    assert pending is not None and pending.status == "PENDING"
    with pytest.raises(ValueError, match="no refresh credential"):
        await service.refresh(pending.connection_id)
    disconnected = await service.disconnect(pending.connection_id)
    assert disconnected.status == "DISCONNECTED"
    with pytest.raises(LookupError, match="does not exist"):
        await service.refresh(UUID(int=0))

    service, connections, _, provider, _ = _service()
    start = await service.begin("owner")
    state = parse_qs(urlparse(start.authorization_url).query)["state"][0]
    active = await service.complete(
        {"state": state, "code": "synthetic-code"}, start.browser_session
    )
    provider.refresh_failure_class = "Transient"
    with pytest.raises(OAuthProviderError, match="Transient"):
        await service.refresh(active.connection_id)
    assert connections.connections[active.connection_id].status.value == "ACTIVE"


async def _activate(service: MicrosoftConnectionService) -> ConnectionStatusView:
    start = await service.begin("owner")
    state = parse_qs(urlparse(start.authorization_url).query)["state"][0]
    return await service.complete({"state": state, "code": "synthetic-code"}, start.browser_session)


@pytest.mark.asyncio
async def test_mail_access_refreshes_rotates_and_returns_expiring_handle() -> None:
    service, _, credentials, provider, clock = _service()
    active = await _activate(service)
    grant = await service.acquire_mail_access(active.connection_id)
    assert grant.user_id == "owner"
    assert grant.mail_credential.reveal(clock.now()) == "access-two"
    assert grant.account_id == "account-id"
    assert provider.refresh_calls == ["refresh-one"]
    assert len(credentials.records) == 1


@pytest.mark.asyncio
async def test_mail_access_guards_state_and_marks_auth_failure() -> None:
    service, connections, _, provider, _ = _service()
    pending = await service.begin("owner")
    connection = next(iter(connections.connections.values()))
    with pytest.raises(ConnectionUnavailableError, match="not available"):
        await service.acquire_mail_access(connection.connection_id)

    state = parse_qs(urlparse(pending.authorization_url).query)["state"][0]
    active = await service.complete(
        {"state": state, "code": "synthetic-code"}, pending.browser_session
    )
    provider.refresh_failure_class = "Authentication"
    with pytest.raises(OAuthProviderError, match="Authentication"):
        await service.acquire_mail_access(active.connection_id)
    assert connections.connections[active.connection_id].status.value == "REAUTH_REQUIRED"


@pytest.mark.asyncio
async def test_sync_completion_and_explicit_reauth_update_connection() -> None:
    service, connections, _, _, clock = _service()
    active = await _activate(service)
    completed_at = clock.now()
    await service.mark_sync_succeeded(active.connection_id, completed_at)
    persisted = connections.connections[active.connection_id]
    assert persisted.last_synced_at == completed_at
    with pytest.raises(ValueError, match="timezone-aware"):
        await service.mark_sync_succeeded(active.connection_id, datetime(2026, 8, 13))
    await service.mark_sync_reauth_required(active.connection_id)
    assert persisted.status.value == "REAUTH_REQUIRED"
