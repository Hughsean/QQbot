from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from qq_time_agent.adapters.inbound.http.microsoft_oauth import microsoft_oauth_router
from qq_time_agent.adapters.inbound.http.owner_session import OwnerSessionSigner
from qq_time_agent.modules.connections.application.oauth import AuthorizationStart
from qq_time_agent.modules.connections.contracts import ConnectionStatusView


@dataclass
class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 8, 13, tzinfo=UTC)


class FakeConnectionService:
    def __init__(self) -> None:
        self.connection_id = uuid4()
        self.callback_parameters: dict[str, str] | None = None

    async def begin(self, user_id: str, connection_id: UUID | None = None) -> AuthorizationStart:
        assert user_id == "owner"
        assert connection_id is None or connection_id == self.connection_id
        return AuthorizationStart("https://login.example.test/authorize", "browser-session")

    async def complete(
        self, callback_parameters: dict[str, str], browser_session: str
    ) -> ConnectionStatusView:
        assert browser_session == "browser-session"
        self.callback_parameters = callback_parameters
        return self._view("ACTIVE")

    async def statuses(self, user_id: str) -> tuple[ConnectionStatusView, ...]:
        assert user_id == "owner"
        return (self._view("ACTIVE"),)

    async def status(self, user_id: str) -> ConnectionStatusView:
        return (await self.statuses(user_id))[0]

    async def disconnect(self, connection_id: UUID, user_id: str = "owner") -> ConnectionStatusView:
        assert user_id == "owner"
        assert connection_id == self.connection_id
        return self._view("DISCONNECTED")

    def _view(self, status: str) -> ConnectionStatusView:
        return ConnectionStatusView(
            self.connection_id,
            "MICROSOFT",
            status,
            ("Mail.Read", "User.Read"),
            "o***@example.test",
            None,
        )


def _client() -> tuple[TestClient, FakeConnectionService, str]:
    signer = OwnerSessionSigner(SecretStr("k" * 32), FixedClock())
    token = signer.issue("owner")
    service = FakeConnectionService()
    app = FastAPI()
    app.include_router(microsoft_oauth_router(service, signer))  # type: ignore[arg-type]
    return TestClient(app, base_url="http://localhost:8000"), service, token


def test_start_requires_owner_session_and_sets_loopback_flow_cookie() -> None:
    client, _, token = _client()
    assert client.get("/oauth/microsoft/start", follow_redirects=False).status_code == 401
    exchange = client.post("/api/v1/owner/session", data={"session": token}, follow_redirects=False)
    assert exchange.status_code == 303
    assert "session=" not in exchange.headers["location"]
    response = client.get("/oauth/microsoft/start", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "https://login.example.test/authorize"
    assert "Secure" not in response.headers["set-cookie"]
    assert "HttpOnly" in response.headers["set-cookie"]


def test_callback_maps_safe_result_and_does_not_return_provider_parameters() -> None:
    client, service, token = _client()
    client.post("/api/v1/owner/session", data={"session": token}, follow_redirects=False)
    client.get("/oauth/microsoft/start", follow_redirects=False)
    response = client.get(
        "/oauth/microsoft/callback",
        params={"state": "synthetic-state", "code": "synthetic-code"},
    )
    assert response.status_code == 200
    assert "synthetic-code" not in response.text
    assert service.callback_parameters == {
        "state": "synthetic-state",
        "code": "synthetic-code",
    }


def test_disconnect_requires_owner_csrf_and_explicit_confirmation() -> None:
    client, service, token = _client()
    client.post("/api/v1/owner/session", data={"session": token}, follow_redirects=False)
    start = client.get("/oauth/microsoft/start", follow_redirects=False)
    csrf = start.cookies["qq_time_agent_csrf"]
    payload = {"connection_id": str(service.connection_id), "confirmed": True}
    assert client.post("/api/v1/oauth/microsoft/disconnect", json=payload).status_code == 403
    response = client.post(
        "/api/v1/oauth/microsoft/disconnect",
        json=payload,
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "DISCONNECTED"


def test_owner_bootstrap_page_is_local_only_and_never_places_session_in_url() -> None:
    client, _, _ = _client()
    public_client = TestClient(client.app, base_url="https://agent.example.test")
    assert public_client.get("/oauth/microsoft/owner-start").status_code == 404
    response = client.get("/oauth/microsoft/owner-start")
    assert response.status_code == 200
    assert 'method="post"' in response.text
    assert 'action="/api/v1/owner/session"' in response.text
    assert "session=" not in response.text
    assert "document.forms[0].submit()" in response.text
    csp = response.headers["Content-Security-Policy"]
    assert "script-src 'nonce-" in csp
    assert "form-action 'self'" in csp
    assert "form-action *" not in csp
    assert response.headers["Cache-Control"] == "no-store"


def test_all_oauth_and_connection_routes_reject_non_loopback_host() -> None:
    client, service, token = _client()
    public = TestClient(client.app, base_url="https://agent.example.test")
    assert public.post("/api/v1/owner/session", data={"session": token}).status_code == 404
    assert public.get("/oauth/microsoft/start").status_code == 404
    assert public.get("/oauth/microsoft/callback").status_code == 404
    assert (
        public.get(
            "/api/v1/connections/microsoft/status", headers={"X-Owner-Session": token}
        ).status_code
        == 404
    )
    assert (
        public.post(
            "/api/v1/oauth/microsoft/disconnect",
            json={"connection_id": str(service.connection_id), "confirmed": True},
            headers={"X-Owner-Session": token, "X-CSRF-Token": "synthetic"},
        ).status_code
        == 404
    )


def test_connection_list_returns_safe_multi_account_shape() -> None:
    client, service, token = _client()
    response = client.get("/api/v1/connections/microsoft", headers={"X-Owner-Session": token})
    assert response.status_code == 200
    assert response.json() == [
        {
            "connection_id": str(service.connection_id),
            "provider": "MICROSOFT",
            "status": "ACTIVE",
            "capabilities": ["Mail.Read", "User.Read"],
            "account_mask": "o***@example.test",
            "last_synced_at": None,
            "display_label": "Mailbox",
            "is_default": True,
            "sync_enabled": True,
        }
    ]
