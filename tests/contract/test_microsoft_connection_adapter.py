import json
from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx
import pytest
from pydantic import SecretStr

from qq_time_agent.adapters.outbound.microsoft_graph import connection as connection_module
from qq_time_agent.adapters.outbound.microsoft_graph.connection import (
    SCOPES,
    MicrosoftGraphConnectionAdapter,
)
from qq_time_agent.bootstrap.config_models import MicrosoftConfig
from qq_time_agent.modules.connections.application.ports import OAuthProviderError


@dataclass
class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 8, 13, tzinfo=UTC)


@dataclass
class FakeMsalApplication:
    token_result: dict[str, object]
    begin_calls: list[tuple[list[str], dict[str, object]]] = field(default_factory=list)
    complete_calls: list[tuple[dict[str, object], dict[str, str]]] = field(default_factory=list)
    refresh_calls: list[str] = field(default_factory=list)

    def initiate_auth_code_flow(self, scopes: list[str], **kwargs: object) -> dict[str, object]:
        self.begin_calls.append((scopes, kwargs))
        return {
            "auth_uri": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
            "state": kwargs["state"],
            "code_verifier": "synthetic-verifier",
            "nonce": "synthetic-nonce",
        }

    def acquire_token_by_auth_code_flow(
        self,
        flow: dict[str, object],
        response: dict[str, str],
        **kwargs: object,
    ) -> dict[str, object]:
        self.complete_calls.append((flow, response))
        return self.token_result

    def acquire_token_by_refresh_token(
        self, refresh_token: str, scopes: list[str], **kwargs: object
    ) -> dict[str, object]:
        self.refresh_calls.append(refresh_token)
        return self.token_result


def _config() -> MicrosoftConfig:
    return MicrosoftConfig(
        "common",
        SecretStr("synthetic-client"),
        "http://localhost:8000/oauth/microsoft/callback",
    )


@pytest.mark.asyncio
async def test_adapter_keeps_pkce_nonce_and_provider_dto_inside_boundary() -> None:
    app = FakeMsalApplication(
        {
            "access_token": "synthetic-access",
            "refresh_token": "synthetic-refresh",
            "expires_in": 3600,
        }
    )
    adapter = MicrosoftGraphConnectionAdapter(
        _config(), FixedClock(), application_factory=lambda: app
    )
    authorization = await adapter.begin_authorization("synthetic-state")
    flow = json.loads(authorization.flow_state.get_secret_value())
    assert flow["code_verifier"] == "synthetic-verifier"
    assert flow["nonce"] == "synthetic-nonce"
    assert app.begin_calls[0][0] == SCOPES == ["User.Read", "Mail.Read", "email"]
    assert app.begin_calls[0][1]["redirect_uri"] == (
        "http://localhost:8000/oauth/microsoft/callback"
    )

    tokens = await adapter.complete_authorization(
        authorization.flow_state.get_secret_value(),
        {"state": "synthetic-state", "code": "synthetic-code"},
    )
    assert tokens.refresh_token is not None
    assert "synthetic-refresh" not in repr(tokens)


@pytest.mark.asyncio
async def test_adapter_builds_public_client_without_client_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = FakeMsalApplication({})
    calls: list[tuple[str, dict[str, object]]] = []

    def public_client(client_id: str, **kwargs: object) -> FakeMsalApplication:
        calls.append((client_id, kwargs))
        return app

    monkeypatch.setattr(connection_module.msal, "PublicClientApplication", public_client)
    adapter = MicrosoftGraphConnectionAdapter(_config(), FixedClock())
    await adapter.begin_authorization("synthetic-state")
    await adapter.close()
    assert calls[0][0] == "synthetic-client"
    assert "client_credential" not in calls[0][1]


@pytest.mark.asyncio
async def test_adapter_maps_oauth_error_without_exposing_description() -> None:
    app = FakeMsalApplication(
        {"error": "invalid_grant", "error_description": "sensitive provider detail"}
    )
    adapter = MicrosoftGraphConnectionAdapter(
        _config(), FixedClock(), application_factory=lambda: app
    )
    with pytest.raises(OAuthProviderError) as error:
        await adapter.refresh("synthetic-refresh")
    assert error.value.failure_class == "Authentication"
    assert "sensitive provider detail" not in str(error.value)


@pytest.mark.asyncio
async def test_graph_profile_maps_only_stable_fields() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer synthetic-access"
        return httpx.Response(
            200,
            json={
                "id": "account-id",
                "displayName": "Owner",
                "mail": None,
                "userPrincipalName": "owner@example.test",
                "providerSpecific": "must-not-cross",
            },
        )

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://graph.microsoft.com"
    )
    adapter = MicrosoftGraphConnectionAdapter(_config(), FixedClock(), async_client=client)
    profile = await adapter.get_profile("synthetic-access")
    await client.aclose()
    assert profile.account_id == "account-id"
    assert profile.email == "owner@example.test"
    assert not hasattr(profile, "providerSpecific")


@pytest.mark.asyncio
async def test_graph_401_is_authentication_failure() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(401)

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://graph.microsoft.com"
    )
    adapter = MicrosoftGraphConnectionAdapter(
        _config(), FixedClock(), async_client=client, max_attempts=1
    )
    with pytest.raises(OAuthProviderError) as error:
        await adapter.get_profile("synthetic-access")
    await client.aclose()
    assert error.value.failure_class == "Authentication"
