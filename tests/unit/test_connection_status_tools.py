from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

import pytest

from qq_time_agent.modules.connections.application.ports import ConnectionRepository
from qq_time_agent.modules.connections.application.status import (
    ConnectionStatusQueryService,
    ConnectionStatusResult,
    resolve_provider_phrase,
)
from qq_time_agent.modules.connections.application.tools import ConnectionStatusToolRegistry
from qq_time_agent.modules.connections.domain.models import (
    ConnectionProvider,
    ConnectionStatus,
    ExternalConnection,
)


@dataclass
class Repository:
    values: tuple[ExternalConnection, ...] = ()
    queries: list[tuple[str, str]] = field(default_factory=list)

    async def list_for_provider(
        self, user_id: str, provider: str
    ) -> tuple[ExternalConnection, ...]:
        self.queries.append((user_id, provider))
        return tuple(
            value
            for value in self.values
            if value.user_id == user_id and value.provider.value == provider
        )


@pytest.mark.parametrize(
    ("phrase", "provider"),
    [
        ("QQ邮箱", "QQ_MAIL"),
        ("QQ Mail", "QQ_MAIL"),
        ("QQMail", "QQ_MAIL"),
        ("请检查 QQ 邮箱是否正常", "QQ_MAIL"),
        ("owner@qq.com 的邮箱", "QQ_MAIL"),
        ("Outlook", "MICROSOFT"),
        ("Microsoft邮箱", "MICROSOFT"),
        ("Hotmail 是否正常", "MICROSOFT"),
        ("Office 365 邮件", "MICROSOFT"),
    ],
)
def test_provider_aliases_are_scoped(phrase: str, provider: str) -> None:
    resolved = resolve_provider_phrase(phrase)
    assert resolved.result is ConnectionStatusResult.OK
    assert resolved.provider == provider


@pytest.mark.parametrize("phrase", ["", "QQ", "邮箱", "邮件", "mail", "email"])
def test_generic_provider_phrases_are_ambiguous(phrase: str) -> None:
    resolved = resolve_provider_phrase(phrase)
    assert resolved.result is ConnectionStatusResult.AMBIGUOUS_PROVIDER
    assert resolved.provider is None


def test_unknown_and_conflicting_provider_phrases_are_not_guessed() -> None:
    unknown = resolve_provider_phrase("Gmail")
    assert unknown.result is ConnectionStatusResult.UNKNOWN_PROVIDER
    assert unknown.provider is None

    conflicting = resolve_provider_phrase("QQ邮箱和Outlook")
    assert conflicting.result is ConnectionStatusResult.AMBIGUOUS_PROVIDER
    assert conflicting.provider is None


def test_email_address_is_redacted_from_requested_provider() -> None:
    resolved = resolve_provider_phrase("检查 private.owner@qq.com 是否正常")
    assert resolved.provider == "QQ_MAIL"
    assert resolved.phrase == "检查 ***@qq.com 是否正常"


@pytest.mark.asyncio
async def test_target_provider_is_queried_without_cross_provider_fallback() -> None:
    microsoft = _connection(ConnectionProvider.MICROSOFT, ConnectionStatus.ACTIVE)
    repository = Repository((microsoft,))
    service = ConnectionStatusQueryService(cast(ConnectionRepository, repository))

    snapshot = await service.query("owner", "QQ邮箱")

    assert repository.queries == [("owner", "QQ_MAIL")]
    assert snapshot.result is ConnectionStatusResult.NOT_CONFIGURED
    assert snapshot.provider == "QQ_MAIL"
    assert snapshot.connections == ()


@pytest.mark.asyncio
async def test_unknown_or_ambiguous_provider_does_not_query_repository() -> None:
    repository = Repository()
    service = ConnectionStatusQueryService(cast(ConnectionRepository, repository))

    ambiguous = await service.query("owner", "邮箱")
    unknown = await service.query("owner", "Gmail")
    assert ambiguous.result is ConnectionStatusResult.AMBIGUOUS_PROVIDER
    assert unknown.result is ConnectionStatusResult.UNKNOWN_PROVIDER
    assert repository.queries == []


@pytest.mark.asyncio
async def test_tool_returns_all_safe_persisted_connection_metadata() -> None:
    first = _connection(
        ConnectionProvider.QQ_MAIL,
        ConnectionStatus.ACTIVE,
        account_mask="o***@qq.com",
        capabilities=frozenset({"Mail.Send", "Mail.Read"}),
        last_synced_at=datetime(2026, 8, 28, 8, 30, tzinfo=UTC),
    )
    second = _connection(
        ConnectionProvider.QQ_MAIL,
        ConnectionStatus.REAUTH_REQUIRED,
        account_mask=None,
        capabilities=frozenset(),
        last_synced_at=None,
        is_default=False,
        sync_enabled=False,
    )
    repository = Repository((first, second))
    tools = ConnectionStatusToolRegistry(
        ConnectionStatusQueryService(cast(ConnectionRepository, repository))
    )

    value = await tools.call("owner", "query_external_service_status", {"provider": "QQ邮箱"})

    assert isinstance(value, dict)
    assert repository.queries == [("owner", "QQ_MAIL")]
    assert value == {
        "requested_provider": "QQ邮箱",
        "result": "OK",
        "provider": "QQ_MAIL",
        "status_source": "PERSISTED_CONNECTION_METADATA",
        "live_checked": False,
        "connection_count": 2,
        "connections": [
            {
                "connection_id": str(first.connection_id),
                "provider": "QQ_MAIL",
                "status": "ACTIVE",
                "capabilities": ["Mail.Read", "Mail.Send"],
                "account_mask": "o***@qq.com",
                "last_synced_at": "2026-08-28T08:30:00+00:00",
                "display_label": "Qq Mail",
                "is_default": True,
                "sync_enabled": True,
            },
            {
                "connection_id": str(second.connection_id),
                "provider": "QQ_MAIL",
                "status": "REAUTH_REQUIRED",
                "capabilities": [],
                "account_mask": None,
                "last_synced_at": None,
                "display_label": "Qq Mail",
                "is_default": False,
                "sync_enabled": False,
            },
        ],
    }
    serialized = repr(value)
    assert "provider-account-id" not in serialized
    assert "credential" not in serialized
    assert "account-fingerprint" not in serialized


@pytest.mark.parametrize(
    "status",
    [
        ConnectionStatus.PENDING,
        ConnectionStatus.ACTIVE,
        ConnectionStatus.DEGRADED,
        ConnectionStatus.REAUTH_REQUIRED,
        ConnectionStatus.DISCONNECTED,
    ],
)
@pytest.mark.asyncio
async def test_all_persisted_connection_statuses_are_preserved(status: ConnectionStatus) -> None:
    repository = Repository((_connection(ConnectionProvider.MICROSOFT, status),))
    tools = ConnectionStatusToolRegistry(
        ConnectionStatusQueryService(cast(ConnectionRepository, repository))
    )

    value = await tools.call("owner", "query_external_service_status", {"provider": "Outlook"})

    assert isinstance(value, dict)
    connections = value["connections"]
    assert isinstance(connections, list)
    assert connections[0]["status"] == status.value


@pytest.mark.asyncio
async def test_tool_schema_and_arguments_are_strict() -> None:
    tools = ConnectionStatusToolRegistry(
        ConnectionStatusQueryService(cast(ConnectionRepository, Repository()))
    )
    definition = tools.definitions()[0]
    assert definition.name == "query_external_service_status"
    assert definition.input_schema["required"] == ["provider"]
    assert definition.input_schema["additionalProperties"] is False
    assert "not proof" in definition.description

    invalid = [
        ("unknown", {"provider": "QQ邮箱"}),
        ("query_external_service_status", {}),
        ("query_external_service_status", {"provider": ""}),
        ("query_external_service_status", {"provider": 1}),
        ("query_external_service_status", {"provider": "QQ邮箱", "owner_id": "other"}),
        ("query_external_service_status", {"provider": "x" * 81}),
    ]
    for name, arguments in invalid:
        with pytest.raises(ValueError):
            await tools.call("owner", name, cast(Mapping[str, object], arguments))


def _connection(
    provider: ConnectionProvider,
    status: ConnectionStatus,
    *,
    account_mask: str | None = "a***@example.test",
    capabilities: frozenset[str] = frozenset({"Mail.Read"}),
    last_synced_at: datetime | None = None,
    is_default: bool = True,
    sync_enabled: bool = True,
) -> ExternalConnection:
    return ExternalConnection(
        uuid4(),
        "owner",
        provider,
        status,
        provider_account_id="provider-account-id",
        account_mask=account_mask,
        capabilities=capabilities,
        credential_ref=UUID("11111111-1111-1111-1111-111111111111"),
        last_synced_at=last_synced_at,
        account_fingerprint="account-fingerprint",
        display_label=provider.value.replace("_", " ").title(),
        is_default=is_default,
        sync_enabled=sync_enabled,
    )
