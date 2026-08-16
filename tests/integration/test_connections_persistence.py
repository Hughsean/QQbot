import hashlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from qq_time_agent.adapters.outbound.persistence.database import create_database_engine
from qq_time_agent.bootstrap.settings import load_runtime_config
from qq_time_agent.modules.connections.domain.models import (
    ConnectionProvider,
    ExternalConnection,
    OAuthTransaction,
)
from qq_time_agent.modules.connections.infrastructure.repository import SqlConnectionRepository
from qq_time_agent.modules.connections.infrastructure.tables import (
    ConnectionRow,
    OAuthTransactionRow,
)
from qq_time_agent.modules.credentials.application.vault import VaultService
from qq_time_agent.modules.credentials.contracts import CredentialKind
from qq_time_agent.modules.credentials.infrastructure.cipher import AesGcmCredentialCipher
from qq_time_agent.modules.credentials.infrastructure.repository import SqlCredentialRepository
from qq_time_agent.modules.credentials.infrastructure.tables import CredentialRow

pytestmark = pytest.mark.integration


class FixedClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def now(self) -> datetime:
        return self.value


@pytest_asyncio.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    value = create_database_engine(load_runtime_config().database)
    yield value
    await value.dispose()


@pytest.mark.asyncio
async def test_vault_database_never_contains_plaintext_and_rotation_keeps_reference(
    engine: AsyncEngine,
) -> None:
    config = load_runtime_config()
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    vault = VaultService(
        SqlCredentialRepository(sessions),
        AesGcmCredentialCipher(config.credential_encryption_key),
        FixedClock(datetime(2026, 8, 13, tzinfo=UTC)),
    )
    reference = await vault.store("synthetic-refresh-one", CredentialKind.REFRESH_TOKEN)
    async with sessions() as session:
        row = await session.get(CredentialRow, reference.credential_id)
        assert row is not None
        assert b"synthetic-refresh-one" not in row.ciphertext
    await vault.replace(reference, "synthetic-refresh-two")
    handle = await vault.open(reference)
    assert handle.reveal(datetime(2026, 8, 13, tzinfo=UTC)) == "synthetic-refresh-two"
    assert await vault.delete(reference)


@pytest.mark.asyncio
async def test_qq_mail_connection_persists_only_encrypted_credential_reference(
    engine: AsyncEngine,
) -> None:
    config = load_runtime_config()
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    clock = FixedClock(datetime(2026, 8, 13, tzinfo=UTC))
    vault = VaultService(
        SqlCredentialRepository(sessions),
        AesGcmCredentialCipher(config.credential_encryption_key),
        clock,
    )
    repository = SqlConnectionRepository(sessions)
    secret = "synthetic-qq-mail-authorization-code"
    reference = await vault.store(secret, CredentialKind.IMAP_AUTH_CODE)
    connection = ExternalConnection.start(f"integration-{uuid4()}", ConnectionProvider.QQ_MAIL)
    connection.activate(
        "synthetic-owner@qq.com",
        "s***@qq.com",
        frozenset({"Mail.Read"}),
        reference.credential_id,
    )
    await repository.add(connection)
    try:
        loaded = await repository.get(connection.connection_id)
        assert loaded is not None and loaded.provider is ConnectionProvider.QQ_MAIL
        assert loaded.credential_ref == reference.credential_id
        async with sessions() as session:
            credential = await session.get(CredentialRow, reference.credential_id)
            row = await session.get(ConnectionRow, connection.connection_id)
            assert credential is not None and secret.encode() not in credential.ciphertext
            assert row is not None and not hasattr(row, "authorization_code")
    finally:
        async with sessions.begin() as session:
            await session.execute(
                delete(ConnectionRow).where(ConnectionRow.connection_id == connection.connection_id)
            )
        await vault.delete(reference)


@pytest.mark.asyncio
async def test_oauth_transaction_claim_is_atomic_one_time_and_session_bound(
    engine: AsyncEngine,
) -> None:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    repository = SqlConnectionRepository(sessions)
    now = datetime(2026, 8, 13, tzinfo=UTC)
    connection = ExternalConnection.start("integration-owner", ConnectionProvider.MICROSOFT)
    state_hash = hashlib.sha256(uuid4().bytes).digest()
    browser_hash = hashlib.sha256(uuid4().bytes).digest()
    transaction = OAuthTransaction(
        uuid4(),
        connection.connection_id,
        connection.user_id,
        state_hash,
        browser_hash,
        uuid4(),
        now + timedelta(minutes=10),
        now,
    )
    await repository.add_authorization(connection, transaction)
    assert await repository.claim_transaction(state_hash, b"x" * 32, now) is None
    claimed = await repository.claim_transaction(state_hash, browser_hash, now)
    assert claimed is not None and claimed.consumed_at == now
    assert await repository.claim_transaction(state_hash, browser_hash, now) is None

    loaded = await repository.get(connection.connection_id)
    assert loaded is not None
    loaded.activate("account", "a***@example.test", frozenset({"Mail.Read"}), uuid4())
    await repository.save(loaded, loaded.version - 1)
    persisted = await repository.get_for_provider("integration-owner", "MICROSOFT")
    assert persisted is not None and persisted.status.value == "ACTIVE"

    async with sessions.begin() as session:
        await session.execute(
            delete(OAuthTransactionRow).where(
                OAuthTransactionRow.transaction_id == transaction.transaction_id
            )
        )
        await session.execute(
            delete(ConnectionRow).where(ConnectionRow.connection_id == connection.connection_id)
        )


@pytest.mark.asyncio
async def test_same_provider_connections_are_isolated_by_identity(engine: AsyncEngine) -> None:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    repository = SqlConnectionRepository(sessions)
    user_id = f"multi-{uuid4()}"
    first = ExternalConnection.start(user_id, ConnectionProvider.QQ_MAIL)
    second = ExternalConnection.start(user_id, ConnectionProvider.QQ_MAIL)
    first.bind_identity("v1:" + "1" * 64, "Primary", is_default=True)
    second.bind_identity("v1:" + "2" * 64, "Secondary", is_default=False)
    first.activate("first@qq.com", "f***@qq.com", frozenset({"Mail.Read"}), uuid4())
    second.activate("second@qq.com", "s***@qq.com", frozenset({"Mail.Read"}), uuid4())
    await repository.add(first)
    await repository.add(second)
    try:
        values = await repository.list_for_provider(user_id, ConnectionProvider.QQ_MAIL.value)
        assert {value.connection_id for value in values} == {
            first.connection_id,
            second.connection_id,
        }
        default = await repository.get_for_provider(user_id, ConnectionProvider.QQ_MAIL.value)
        assert default is not None and default.connection_id == first.connection_id
        matched = await repository.get_by_identity(
            user_id, ConnectionProvider.QQ_MAIL.value, second.account_fingerprint or ""
        )
        assert matched is not None and matched.connection_id == second.connection_id
        owned = await repository.get_for_user(first.connection_id, user_id)
        assert owned is not None and owned.display_label == "Primary"
    finally:
        async with sessions.begin() as session:
            await session.execute(
                delete(ConnectionRow).where(
                    ConnectionRow.connection_id.in_((first.connection_id, second.connection_id))
                )
            )
