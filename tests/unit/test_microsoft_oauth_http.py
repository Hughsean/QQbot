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
from qq_time_agent.modules.task_projection.contracts import ManagedTaskListView


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
            ("Mail.Read", "Tasks.ReadWrite", "User.Read"),
            "o***@example.test",
            None,
        )


class FakeTodoSetup:
    def __init__(self) -> None:
        self.calls: list[tuple[str, UUID]] = []

    async def resolve(self, user_id: str, connection_id: UUID) -> ManagedTaskListView:
        self.calls.append((user_id, connection_id))
        return ManagedTaskListView(uuid4(), connection_id, "小智建议", "READY", 1)


def _client(
    todo_setup: FakeTodoSetup | None = None,
) -> tuple[TestClient, FakeConnectionService, str]:
    signer = OwnerSessionSigner(SecretStr("k" * 32), FixedClock())
    token = signer.issue("owner")
    service = FakeConnectionService()
    app = FastAPI()
    app.include_router(  # type: ignore[arg-type]
        microsoft_oauth_router(service, signer, todo_setup)
    )
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


def test_callback_resolves_managed_todo_list_after_authorization() -> None:
    todo_setup = FakeTodoSetup()
    client, service, token = _client(todo_setup)
    client.post("/api/v1/owner/session", data={"session": token}, follow_redirects=False)
    client.get("/oauth/microsoft/start", follow_redirects=False)
    response = client.get(
        "/oauth/microsoft/callback",
        params={"state": "synthetic-state", "code": "synthetic-code"},
    )

    assert response.status_code == 200
    assert "Microsoft To Do list is ready" in response.text
    assert todo_setup.calls == [("owner", service.connection_id)]


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


def test_explicit_todo_resolution_requires_owner_csrf() -> None:
    todo_setup = FakeTodoSetup()
    client, service, token = _client(todo_setup)
    client.post("/api/v1/owner/session", data={"session": token}, follow_redirects=False)
    start = client.get("/oauth/microsoft/start", follow_redirects=False)
    payload = {"connection_id": str(service.connection_id)}
    assert (
        client.post("/api/v1/connections/microsoft/todo/resolve", json=payload).status_code == 403
    )

    response = client.post(
        "/api/v1/connections/microsoft/todo/resolve",
        json=payload,
        headers={"X-CSRF-Token": start.cookies["qq_time_agent_csrf"]},
    )
    assert response.status_code == 200
    assert response.json()["display_name"] == "小智建议"


def test_owner_bootstrap_redirects_without_url_secret() -> None:
    client, _, _ = _client()
    public_client = TestClient(client.app, base_url="https://agent.example.test")
    assert public_client.get("/oauth/microsoft/owner-start").status_code == 404
    response = client.get("/oauth/microsoft/owner-start", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/oauth/microsoft/start?connection_id=")
    assert "qq_time_agent_owner" in response.cookies
    assert response.headers["Cache-Control"] == "no-store"


def test_owner_bootstrap_canonicalizes_127_to_callback_cookie_host() -> None:
    client, _, _ = _client()
    numeric_loopback = TestClient(client.app, base_url="http://127.0.0.1:8000")
    response = numeric_loopback.get("/oauth/microsoft/owner-start", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "http://localhost:8000/oauth/microsoft/owner-start"
    assert "qq_time_agent_owner" not in response.cookies


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
            "capabilities": ["Mail.Read", "Tasks.ReadWrite", "User.Read"],
            "account_mask": "o***@example.test",
            "last_synced_at": None,
            "display_label": "Mailbox",
            "is_default": True,
            "sync_enabled": True,
        }
    ]
