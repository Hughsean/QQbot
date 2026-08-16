from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from qq_time_agent.adapters.inbound.http.owner_session import OwnerSessionSigner
from qq_time_agent.adapters.inbound.http.qq_mail import qq_mail_router
from qq_time_agent.modules.connections.application.qq_mail import QqMailConnectCommand
from qq_time_agent.modules.connections.contracts import ConnectionStatusView


@dataclass
class Clock:
    def now(self) -> datetime:
        return datetime(2026, 8, 13, tzinfo=UTC)


class Service:
    def __init__(self) -> None:
        self.connection_id = uuid4()
        self.command: QqMailConnectCommand | None = None

    async def connect(self, command: QqMailConnectCommand) -> ConnectionStatusView:
        self.command = command
        return self.view("ACTIVE")

    async def statuses(self, user_id: str) -> tuple[ConnectionStatusView, ...]:
        assert user_id == "owner"
        return (self.view("ACTIVE"),)

    async def status(self, user_id: str) -> ConnectionStatusView | None:
        return (await self.statuses(user_id))[0]

    async def disconnect(self, connection_id: UUID, user_id: str = "owner") -> ConnectionStatusView:
        assert user_id == "owner"
        assert connection_id == self.connection_id
        return self.view("DISCONNECTED")

    def view(self, status: str) -> ConnectionStatusView:
        return ConnectionStatusView(
            self.connection_id, "QQ_MAIL", status, ("Mail.Read",), "o***@qq.com", None
        )


def client() -> tuple[TestClient, Service, OwnerSessionSigner]:
    signer = OwnerSessionSigner(SecretStr("k" * 32), Clock())
    service = Service()
    app = FastAPI()
    app.include_router(qq_mail_router(service, signer))  # type: ignore[arg-type]
    return TestClient(app, base_url="http://localhost:8000"), service, signer


def establish_owner(value: TestClient, signer: OwnerSessionSigner) -> str:
    token = signer.issue("owner")
    value.cookies.set("qq_time_agent_owner", token)
    page = value.get("/qq-mail/connect")
    assert page.status_code == 200
    return str(page.cookies["qq_time_agent_csrf"])


def test_connect_requires_loopback_owner_and_csrf() -> None:
    value, service, signer = client()
    payload = {"address": "owner@qq.com", "authorization_code": "not-for-logs-code"}
    assert value.post("/api/v1/connections/qq-mail", json=payload).status_code == 401
    csrf = establish_owner(value, signer)
    assert value.post("/api/v1/connections/qq-mail", json=payload).status_code == 403
    response = value.post(
        "/api/v1/connections/qq-mail",
        json=payload,
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 200 and response.json()["provider"] == "QQ_MAIL"
    assert service.command is not None and service.command.user_id == "owner"
    assert payload["authorization_code"] not in response.text


def test_signed_non_owner_session_is_rejected() -> None:
    value, _, signer = client()
    token = signer.issue("intruder")
    response = value.get("/qq-mail/connect", cookies={"qq_time_agent_owner": token})
    assert response.status_code == 403


def test_routes_are_hidden_on_non_loopback_host() -> None:
    value, service, signer = client()
    public = TestClient(value.app, base_url="https://agent.example.test")
    token = signer.issue("owner")
    assert public.get("/qq-mail/owner-start").status_code == 404
    assert (
        public.get(
            "/api/v1/connections/qq-mail/status",
            cookies={"qq_time_agent_owner": token},
        ).status_code
        == 404
    )
    assert (
        public.post(
            "/api/v1/connections/qq-mail/disconnect",
            json={"connection_id": str(service.connection_id), "confirmed": True},
            cookies={"qq_time_agent_owner": token, "qq_time_agent_csrf": "x"},
            headers={"X-CSRF-Token": "x"},
        ).status_code
        == 404
    )


def test_disconnect_requires_explicit_confirmation() -> None:
    value, service, signer = client()
    csrf = establish_owner(value, signer)
    endpoint = "/api/v1/connections/qq-mail/disconnect"
    assert (
        value.post(
            endpoint,
            json={"connection_id": str(service.connection_id), "confirmed": False},
            headers={"X-CSRF-Token": csrf},
        ).status_code
        == 409
    )
    assert (
        value.post(
            endpoint,
            json={"connection_id": str(service.connection_id), "confirmed": True},
            headers={"X-CSRF-Token": csrf},
        ).json()["status"]
        == "DISCONNECTED"
    )


def test_owner_start_bootstraps_qq_mail_destination_without_url_secret() -> None:
    value, _, _ = client()
    response = value.get("/qq-mail/owner-start")
    assert response.status_code == 200
    assert 'name="next" value="/qq-mail/connect"' in response.text
    assert "session=" not in response.text
    assert response.headers["Cache-Control"] == "no-store"


def test_connection_list_requires_owner_and_returns_safe_shape() -> None:
    value, service, signer = client()
    assert value.get("/api/v1/connections/qq-mail").status_code == 401
    establish_owner(value, signer)
    response = value.get("/api/v1/connections/qq-mail")
    assert response.status_code == 200
    assert response.json()[0]["connection_id"] == str(service.connection_id)
    assert response.json()[0]["display_label"] == "Mailbox"
