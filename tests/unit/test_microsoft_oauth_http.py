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

    async def begin(self, user_id: str) -> AuthorizationStart:
        assert user_id == "owner"
        return AuthorizationStart("https://login.example.test/authorize", "browser-session")

    async def complete(
        self, callback_parameters: dict[str, str], browser_session: str
    ) -> ConnectionStatusView:
        assert browser_session == "browser-session"
        self.callback_parameters = callback_parameters
        return self._view("ACTIVE")

    async def status(self, user_id: str) -> ConnectionStatusView:
        assert user_id == "owner"
        return self._view("ACTIVE")

    async def disconnect(self, connection_id: UUID) -> ConnectionStatusView:
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
    app.include_router(
        microsoft_oauth_router(service, signer, "https://testserver")  # type: ignore[arg-type]
    )
    return TestClient(app, base_url="https://testserver"), service, token


def test_start_requires_owner_session_and_sets_secure_flow_cookie() -> None:
    client, _, token = _client()
    assert client.get("/oauth/microsoft/start", follow_redirects=False).status_code == 401
    exchange = client.post("/api/v1/owner/session", data={"session": token}, follow_redirects=False)
    assert exchange.status_code == 303
    assert "session=" not in exchange.headers["location"]
    response = client.get("/oauth/microsoft/start", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "https://login.example.test/authorize"
    assert "Secure" in response.headers["set-cookie"]
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
    assert client.get("/oauth/microsoft/owner-start").status_code == 404
    local_client = TestClient(client.app, base_url="http://127.0.0.1")
    response = local_client.get("/oauth/microsoft/owner-start")
    assert response.status_code == 200
    assert 'method="post"' in response.text
    assert 'action="/oauth/microsoft/owner-start"' in response.text
    assert "session=" not in response.text
    assert "document.forms[0].submit()" in response.text
    csp = response.headers["Content-Security-Policy"]
    assert "script-src 'nonce-" in csp
    assert "form-action 'self' https://testserver https://login.microsoftonline.com" in csp
    assert "form-action *" not in csp
    assert response.headers["Cache-Control"] == "no-store"
    relay = local_client.post(
        "/oauth/microsoft/owner-start", data={"session": "opaque"}, follow_redirects=False
    )
    assert relay.status_code == 307
    assert relay.headers["location"] == "https://testserver/api/v1/owner/session"
    assert "opaque" not in relay.headers["location"]
