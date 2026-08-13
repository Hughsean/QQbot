from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from qq_time_agent.adapters.inbound.http.mail_sync import mail_sync_router
from qq_time_agent.adapters.inbound.http.owner_session import OwnerSessionSigner
from qq_time_agent.contracts.jobs import JobLease, JobRequest, JobStatusView
from qq_time_agent.modules.connections.contracts import ConnectionStatusView
from qq_time_agent.modules.inbox.contracts import InboxSourceView


@dataclass
class FixedClock:
    value: datetime = datetime(2026, 8, 13, tzinfo=UTC)

    def now(self) -> datetime:
        return self.value


@dataclass
class FakeConnections:
    view: ConnectionStatusView | None

    async def status(self, user_id: str) -> ConnectionStatusView | None:
        assert user_id == "owner"
        return self.view


@dataclass
class FakeInbox:
    source_view: InboxSourceView | None

    async def source(self, inbox_item_id: UUID) -> InboxSourceView | None:
        if self.source_view is not None:
            assert inbox_item_id == self.source_view.inbox_item_id
        return self.source_view


@dataclass
class MemoryQueue:
    clock: FixedClock
    jobs: dict[UUID, JobStatusView] = field(default_factory=dict)
    keys: dict[str, UUID] = field(default_factory=dict)

    async def enqueue(self, request: JobRequest) -> UUID:
        if request.idempotency_key in self.keys:
            return self.keys[request.idempotency_key]
        job_id = uuid4()
        self.keys[request.idempotency_key] = job_id
        self.jobs[job_id] = JobStatusView(
            job_id, request.kind, "PENDING", 0, request.max_attempts, None, self.clock.now()
        )
        return job_id

    async def status(self, job_id: UUID) -> JobStatusView | None:
        return self.jobs.get(job_id)

    async def lease_due(
        self, now: datetime, worker_id: str, limit: int, lease_duration: timedelta
    ) -> list[JobLease]:
        return []

    async def complete(self, lease: JobLease, now: datetime) -> None:
        return None

    async def fail(
        self,
        lease: JobLease,
        now: datetime,
        failure_class: str,
        retry_at: datetime | None,
    ) -> None:
        return None


def _client(
    status_value: str = "ACTIVE",
) -> tuple[TestClient, str, UUID, UUID]:
    clock = FixedClock()
    signer = OwnerSessionSigner(SecretStr("k" * 32), clock)
    token = signer.issue("owner")
    connection_id = uuid4()
    inbox_item_id = uuid4()
    connection = ConnectionStatusView(
        connection_id,
        "MICROSOFT",
        status_value,
        ("Mail.Read", "User.Read"),
        "o***@example.test",
        None,
    )
    source = InboxSourceView(
        inbox_item_id,
        "MICROSOFT_MAIL",
        "message-1",
        "thread-1",
        "s***@example.test",
        "Subject",
        clock.now(),
        "NORMALIZED",
        False,
    )
    app = FastAPI()
    app.include_router(
        mail_sync_router(
            FakeConnections(connection), FakeInbox(source), MemoryQueue(clock), signer, clock, 300
        )
    )
    return TestClient(app, base_url="http://localhost:8000"), token, connection_id, inbox_item_id


def test_sync_http_requires_owner_and_enqueues_idempotently() -> None:
    client, token, connection_id, _ = _client()
    path = f"/api/v1/connections/{connection_id}/sync"
    assert client.post(path).status_code == 401
    first = client.post(path, headers={"X-Owner-Session": token})
    second = client.post(path, headers={"X-Owner-Session": token})
    assert first.status_code == 202
    assert first.json()["job_id"] == second.json()["job_id"]
    job_id = first.json()["job_id"]
    status_response = client.get(f"/api/v1/sync-jobs/{job_id}", headers={"X-Owner-Session": token})
    assert status_response.json()["status"] == "PENDING"
    assert "payload" not in status_response.json()


def test_sync_rejects_disconnected_connection() -> None:
    client, token, connection_id, _ = _client("DISCONNECTED")
    response = client.post(
        f"/api/v1/connections/{connection_id}/sync",
        headers={"X-Owner-Session": token},
    )
    assert response.status_code == 409


def test_source_trace_view_never_returns_body_or_recipients() -> None:
    client, token, _, inbox_item_id = _client()
    response = client.get(
        f"/api/v1/inbox/{inbox_item_id}/source", headers={"X-Owner-Session": token}
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["sender_mask"] == "s***@example.test"
    assert "body" not in payload
    assert "recipients" not in payload
    assert "cursor" not in payload
