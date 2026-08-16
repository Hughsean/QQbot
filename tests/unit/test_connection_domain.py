import hashlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from qq_time_agent.modules.connections.domain.models import (
    ConnectionProvider,
    ConnectionStatus,
    ExternalConnection,
    OAuthTransaction,
)


def test_connection_requires_credential_deletion_before_disconnect() -> None:
    connection = ExternalConnection.start("owner", ConnectionProvider.MICROSOFT)
    credential_id = uuid4()
    connection.activate("account", "a***@example.test", frozenset({"Mail.Read"}), credential_id)
    with pytest.raises(ValueError, match="credential must be deleted"):
        connection.disconnect(False)
    connection.disconnect(True)
    assert connection.status is ConnectionStatus.DISCONNECTED
    assert connection.credential_ref is None


def test_connection_rejects_invalid_identity_and_activation_inputs() -> None:
    with pytest.raises(ValueError, match="user_id is required"):
        ExternalConnection.start(" ", ConnectionProvider.MICROSOFT)
    connection = ExternalConnection.start("owner", ConnectionProvider.MICROSOFT)
    with pytest.raises(ValueError, match="provider account and capabilities"):
        connection.activate("", "account", frozenset(), uuid4())
    connection.disconnect(True)
    with pytest.raises(ValueError, match="cannot be activated"):
        connection.activate("account", "account", frozenset({"Mail.Read"}), uuid4())


def test_connection_reauthorization_transitions_respect_terminal_states() -> None:
    connection = ExternalConnection.start("owner", ConnectionProvider.MICROSOFT)
    connection.require_reauthorization(datetime(2026, 8, 13, tzinfo=UTC))
    assert connection.status is ConnectionStatus.REAUTH_REQUIRED
    connection.restart_authorization()
    assert connection.status.value == "PENDING"
    connection.activate("account", "account", frozenset({"Mail.Read"}), uuid4())
    with pytest.raises(ValueError, match="active connection"):
        connection.restart_authorization()
    connection.disconnect(True)
    version = connection.version
    connection.require_reauthorization(datetime(2026, 8, 13, tzinfo=UTC))
    assert connection.status.value == "DISCONNECTED"
    assert connection.version == version


def test_connection_identity_binding_is_stable_and_sync_is_explicit() -> None:
    connection = ExternalConnection.start("owner", ConnectionProvider.QQ_MAIL)
    connection.bind_identity("v1:" + "a" * 64, "Personal mail", is_default=False)
    assert connection.display_label == "Personal mail"
    assert not connection.is_default

    with pytest.raises(ValueError, match="identity cannot change"):
        connection.bind_identity("v1:" + "b" * 64, "Other", is_default=False)

    connection.set_sync_enabled(False)
    assert not connection.sync_enabled
    connection.disconnect(True)
    with pytest.raises(ValueError, match="cannot enable"):
        connection.set_sync_enabled(True)


def test_oauth_transaction_is_session_bound_expiring_and_one_time() -> None:
    now = datetime(2026, 8, 13, tzinfo=UTC)
    state_hash = hashlib.sha256(b"state").digest()
    browser_hash = hashlib.sha256(b"browser").digest()
    transaction = OAuthTransaction(
        uuid4(),
        uuid4(),
        "owner",
        state_hash,
        browser_hash,
        uuid4(),
        now + timedelta(minutes=5),
        now,
    )
    with pytest.raises(ValueError, match="state mismatch"):
        transaction.claim(hashlib.sha256(b"wrong").digest(), browser_hash, now)
    with pytest.raises(ValueError, match="browser session"):
        transaction.claim(state_hash, hashlib.sha256(b"wrong").digest(), now)
    transaction.claim(state_hash, browser_hash, now)
    with pytest.raises(ValueError, match="already consumed"):
        transaction.claim(state_hash, browser_hash, now)


def test_oauth_transaction_rejects_expired_and_naive_claim_times() -> None:
    now = datetime(2026, 8, 13, tzinfo=UTC)
    state_hash = hashlib.sha256(b"state").digest()
    browser_hash = hashlib.sha256(b"browser").digest()
    transaction = OAuthTransaction(
        uuid4(), uuid4(), "owner", state_hash, browser_hash, uuid4(), now, now
    )
    with pytest.raises(ValueError, match="expired"):
        transaction.claim(state_hash, browser_hash, now)
    with pytest.raises(ValueError, match="timezone-aware"):
        transaction.claim(state_hash, browser_hash, datetime(2026, 8, 13))
