"""Thin authenticated HTTP mapping for asynchronous mail synchronization."""

from datetime import datetime
from typing import Annotated, Protocol
from uuid import UUID

from fastapi import APIRouter, Cookie, Header, HTTPException, status

from qq_time_agent.adapters.inbound.http.microsoft_oauth import OWNER_COOKIE
from qq_time_agent.adapters.inbound.http.owner_session import (
    OwnerAuthenticationError,
    OwnerSessionSigner,
)
from qq_time_agent.contracts.clock import Clock
from qq_time_agent.contracts.jobs import JobQueue, JobRequest, JobStatusView
from qq_time_agent.modules.connections.contracts import ConnectionStatusView
from qq_time_agent.modules.inbox.contracts import InboxSourceView

MAIL_SYNC_JOB = "microsoft-mail-sync"


class ConnectionLookup(Protocol):
    async def status(self, user_id: str) -> ConnectionStatusView | None: ...


class InboxSourceLookup(Protocol):
    async def source(self, inbox_item_id: UUID) -> InboxSourceView | None: ...


def mail_sync_router(
    connections: ConnectionLookup,
    inbox: InboxSourceLookup,
    queue: JobQueue,
    signer: OwnerSessionSigner,
    clock: Clock,
    interval_seconds: int,
) -> APIRouter:
    if interval_seconds < 60:
        raise ValueError("mail sync interval must be at least 60 seconds")
    router = APIRouter()

    @router.post("/api/v1/connections/{connection_id}/sync", status_code=status.HTTP_202_ACCEPTED)
    async def enqueue_sync(
        connection_id: UUID,
        owner_cookie: Annotated[str | None, Cookie(alias=OWNER_COOKIE)] = None,
        owner_header: Annotated[str | None, Header(alias="X-Owner-Session")] = None,
    ) -> JobStatusView:
        owner_id = _authenticate(signer, owner_header or owner_cookie or "")
        view = await connections.status(owner_id)
        if view is None or view.connection_id != connection_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "connection not found")
        if view.status not in {"ACTIVE", "DEGRADED"}:
            raise HTTPException(status.HTTP_409_CONFLICT, "connection is not available")
        now = clock.now()
        job_id = await queue.enqueue(
            JobRequest(
                MAIL_SYNC_JOB,
                {"connection_id": str(connection_id)},
                _idempotency_key(connection_id, now, interval_seconds),
                now,
            )
        )
        result = await queue.status(job_id)
        if result is None:
            raise RuntimeError("enqueued sync job is missing")
        return result

    @router.get("/api/v1/sync-jobs/{job_id}", response_model=JobStatusView)
    async def sync_status(
        job_id: UUID,
        owner_cookie: Annotated[str | None, Cookie(alias=OWNER_COOKIE)] = None,
        owner_header: Annotated[str | None, Header(alias="X-Owner-Session")] = None,
    ) -> JobStatusView:
        _authenticate(signer, owner_header or owner_cookie or "")
        result = await queue.status(job_id)
        if result is None or result.kind != MAIL_SYNC_JOB:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "sync job not found")
        return result

    @router.get("/api/v1/inbox/{inbox_item_id}/source", response_model=InboxSourceView)
    async def inbox_source(
        inbox_item_id: UUID,
        owner_cookie: Annotated[str | None, Cookie(alias=OWNER_COOKIE)] = None,
        owner_header: Annotated[str | None, Header(alias="X-Owner-Session")] = None,
    ) -> InboxSourceView:
        _authenticate(signer, owner_header or owner_cookie or "")
        result = await inbox.source(inbox_item_id)
        if result is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Inbox source not found")
        return result

    return router


def _authenticate(signer: OwnerSessionSigner, token: str) -> str:
    try:
        return signer.verify(token).user_id
    except OwnerAuthenticationError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "owner authentication required") from exc


def _idempotency_key(connection_id: UUID, now: datetime, interval_seconds: int) -> str:
    bucket = int(now.timestamp()) // interval_seconds
    return f"mail-sync:{connection_id}:{bucket}"
