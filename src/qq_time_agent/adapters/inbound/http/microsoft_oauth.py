"""Thin HTTP mapping for Microsoft delegated OAuth lifecycle."""

import logging
import secrets
from typing import Annotated
from urllib.parse import parse_qs
from uuid import UUID

from fastapi import APIRouter, Cookie, Header, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from qq_time_agent.adapters.inbound.http.owner_session import (
    OwnerAuthenticationError,
    OwnerSession,
    OwnerSessionSigner,
    verify_csrf,
)
from qq_time_agent.modules.connections.application.oauth import (
    MicrosoftConnectionService,
    OAuthSecurityError,
)
from qq_time_agent.modules.connections.application.ports import OAuthProviderError
from qq_time_agent.modules.connections.contracts import ConnectionStatusView
from qq_time_agent.modules.task_projection.application import (
    ManagedTaskListAmbiguousError,
    ManagedTaskListNotFoundError,
    ManagedTaskListOwnershipError,
)
from qq_time_agent.modules.task_projection.contracts import (
    ManagedTaskListSetupPort,
    ManagedTaskListView,
    TaskProviderError,
)

OWNER_COOKIE = "qq_time_agent_owner"
OAUTH_COOKIE = "qq_time_agent_oauth"
CSRF_COOKIE = "qq_time_agent_csrf"
_LOGGER = logging.getLogger(__name__)


class DisconnectRequest(BaseModel):
    connection_id: str
    confirmed: bool


class TodoSetupRequest(BaseModel):
    connection_id: UUID


def microsoft_oauth_router(
    service: MicrosoftConnectionService,
    signer: OwnerSessionSigner,
    todo_setup: ManagedTaskListSetupPort | None = None,
) -> APIRouter:
    router = APIRouter()
    router.include_router(_owner_bootstrap_router(service, signer))
    router.include_router(_oauth_flow_router(service, signer, todo_setup))
    router.include_router(_connection_api_router(service, signer))
    if todo_setup is not None:
        router.include_router(_todo_setup_router(todo_setup, signer))
    return router


def _owner_bootstrap_router(
    service: MicrosoftConnectionService, signer: OwnerSessionSigner
) -> APIRouter:
    router = APIRouter()

    @router.get("/oauth/microsoft/owner-start", response_class=RedirectResponse)
    async def owner_start(request: Request) -> RedirectResponse:
        _require_loopback_request(request)
        if request.url.hostname == "127.0.0.1":
            response = RedirectResponse(
                _canonical_owner_start_url(request), status.HTTP_303_SEE_OTHER
            )
            _secure_redirect(response)
            return response
        token = signer.issue("owner")
        next_path = await _default_authorization_path(service)
        response = RedirectResponse(next_path, status.HTTP_303_SEE_OTHER)
        _set_loopback_cookie(response, OWNER_COOKIE, token, httponly=True)
        _secure_redirect(response)
        return response

    @router.post("/api/v1/owner/session", response_class=RedirectResponse)
    async def establish_owner_session(request: Request) -> RedirectResponse:
        _require_loopback_request(request)
        body = await request.body()
        if len(body) > 4096:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "request is too large")
        try:
            form = parse_qs(body.decode("ascii"), strict_parsing=True)
            token = form["session"][0]
            next_path = form.get("next", ["/oauth/microsoft/start"])[0]
        except (UnicodeDecodeError, ValueError, KeyError, IndexError) as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid session request") from exc
        _authenticate(signer, token)
        if next_path not in {"/oauth/microsoft/start", "/qq-mail/connect"}:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid session destination")
        response = RedirectResponse(next_path, status.HTTP_303_SEE_OTHER)
        _set_loopback_cookie(response, OWNER_COOKIE, token, httponly=True)
        return response

    return router


def _oauth_flow_router(
    service: MicrosoftConnectionService,
    signer: OwnerSessionSigner,
    todo_setup: ManagedTaskListSetupPort | None,
) -> APIRouter:
    router = APIRouter()

    @router.get("/oauth/microsoft/start", response_class=RedirectResponse)
    async def start(
        request: Request,
        owner_cookie: Annotated[str | None, Cookie(alias=OWNER_COOKIE)] = None,
        connection_id: UUID | None = None,
    ) -> RedirectResponse:
        _require_loopback_request(request)
        owner_token = owner_cookie or ""
        owner = _authenticate(signer, owner_token)
        authorization = await service.begin(owner.user_id, connection_id)
        response = RedirectResponse(authorization.authorization_url, status.HTTP_302_FOUND)
        _set_loopback_cookie(response, OWNER_COOKIE, owner_token, httponly=True)
        _set_loopback_cookie(response, OAUTH_COOKIE, authorization.browser_session, httponly=True)
        _set_loopback_cookie(response, CSRF_COOKIE, secrets.token_urlsafe(24), httponly=False)
        return response

    @router.get("/oauth/microsoft/callback", response_class=HTMLResponse)
    async def callback(
        request: Request,
        oauth_cookie: Annotated[str | None, Cookie(alias=OAUTH_COOKIE)] = None,
    ) -> HTMLResponse:
        _require_loopback_request(request)
        parameters = {key: value for key, value in request.query_params.items()}
        try:
            view = await service.complete(parameters, oauth_cookie or "")
        except OAuthProviderError as exc:
            _LOGGER.warning(
                "Microsoft OAuth callback rejected",
                extra={"failure_class": exc.failure_class},
            )
            response = _failed_callback_response()
        except OAuthSecurityError:
            _LOGGER.warning(
                "Microsoft OAuth callback rejected", extra={"failure_class": "SecurityPolicy"}
            )
            response = _failed_callback_response()
        except (LookupError, ValueError):
            _LOGGER.warning(
                "Microsoft OAuth callback rejected", extra={"failure_class": "ConnectionConflict"}
            )
            response = _failed_callback_response()
        else:
            response = await _successful_callback_response(view, todo_setup)
        response.delete_cookie(OAUTH_COOKIE, secure=False, httponly=True, samesite="lax")
        return response

    return router


def _connection_api_router(
    service: MicrosoftConnectionService,
    signer: OwnerSessionSigner,
) -> APIRouter:
    router = APIRouter()

    @router.get(
        "/api/v1/connections/microsoft",
        response_model=list[ConnectionStatusView],
    )
    async def connection_list(
        request: Request,
        owner_cookie: Annotated[str | None, Cookie(alias=OWNER_COOKIE)] = None,
        owner_header: Annotated[str | None, Header(alias="X-Owner-Session")] = None,
    ) -> tuple[ConnectionStatusView, ...]:
        _require_loopback_request(request)
        owner = _authenticate(signer, owner_header or owner_cookie or "")
        return await service.statuses(owner.user_id)

    @router.get(
        "/api/v1/connections/microsoft/status",
        response_model=ConnectionStatusView | None,
    )
    async def connection_status(
        request: Request,
        owner_cookie: Annotated[str | None, Cookie(alias=OWNER_COOKIE)] = None,
        owner_header: Annotated[str | None, Header(alias="X-Owner-Session")] = None,
    ) -> ConnectionStatusView | None:
        _require_loopback_request(request)
        owner = _authenticate(signer, owner_header or owner_cookie or "")
        return await service.status(owner.user_id)

    @router.post("/api/v1/oauth/microsoft/disconnect", response_model=ConnectionStatusView)
    async def disconnect(
        request: Request,
        payload: DisconnectRequest,
        owner_cookie: Annotated[str | None, Cookie(alias=OWNER_COOKIE)] = None,
        owner_header: Annotated[str | None, Header(alias="X-Owner-Session")] = None,
        csrf_cookie: Annotated[str | None, Cookie(alias=CSRF_COOKIE)] = None,
        csrf_header: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
    ) -> ConnectionStatusView:
        _require_loopback_request(request)
        owner = _authenticate(signer, owner_header or owner_cookie or "")
        try:
            verify_csrf(csrf_cookie, csrf_header)
        except OwnerAuthenticationError as exc:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "request verification failed") from exc
        if not payload.confirmed:
            raise HTTPException(status.HTTP_409_CONFLICT, "disconnect requires confirmation")
        try:
            connection_id = UUID(payload.connection_id)
        except ValueError as exc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid connection"
            ) from exc
        return await service.disconnect(connection_id, owner.user_id)

    return router


def _todo_setup_router(
    todo_setup: ManagedTaskListSetupPort, signer: OwnerSessionSigner
) -> APIRouter:
    router = APIRouter()

    @router.post(
        "/api/v1/connections/microsoft/todo/resolve",
        response_model=ManagedTaskListView,
    )
    async def resolve_todo_list(
        request: Request,
        payload: TodoSetupRequest,
        owner_cookie: Annotated[str | None, Cookie(alias=OWNER_COOKIE)] = None,
        owner_header: Annotated[str | None, Header(alias="X-Owner-Session")] = None,
        csrf_cookie: Annotated[str | None, Cookie(alias=CSRF_COOKIE)] = None,
        csrf_header: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
    ) -> ManagedTaskListView:
        _require_loopback_request(request)
        owner = _authenticate(signer, owner_header or owner_cookie or "")
        try:
            verify_csrf(csrf_cookie, csrf_header)
        except OwnerAuthenticationError as exc:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "request verification failed") from exc
        try:
            return await todo_setup.resolve(owner.user_id, payload.connection_id)
        except LookupError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "connection does not exist") from exc
        except (
            ManagedTaskListNotFoundError,
            ManagedTaskListAmbiguousError,
            ManagedTaskListOwnershipError,
        ) as exc:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "To Do list could not be verified"
            ) from exc
        except (OAuthProviderError, TaskProviderError) as exc:
            _LOGGER.warning(
                "Microsoft To Do list resolution failed",
                extra={"failure_class": exc.failure_class},
            )
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, "To Do list could not be verified"
            ) from exc

    return router


async def _successful_callback_response(
    view: ConnectionStatusView, todo_setup: ManagedTaskListSetupPort | None
) -> HTMLResponse:
    base = f"Microsoft connection is {view.status.lower()}."
    if todo_setup is None:
        return HTMLResponse(f"{base} You may close this window.")
    try:
        await todo_setup.resolve("owner", view.connection_id)
    except Exception as exc:
        failure_class = getattr(exc, "failure_class", type(exc).__name__)
        _LOGGER.warning(
            "Microsoft To Do list resolution failed",
            extra={"failure_class": failure_class},
        )
        return HTMLResponse(f"{base} To Do list could not be verified. Return to QQ and try again.")
    return HTMLResponse(f"{base} Microsoft To Do list is ready. You may close this window.")


async def _default_authorization_path(service: MicrosoftConnectionService) -> str:
    current = await service.status("owner")
    if current is None or current.status == "DISCONNECTED":
        return "/oauth/microsoft/start"
    return f"/oauth/microsoft/start?connection_id={current.connection_id}"


def _canonical_owner_start_url(request: Request) -> str:
    port = request.url.port
    authority = "localhost" if port is None else f"localhost:{port}"
    return f"http://{authority}/oauth/microsoft/owner-start"


def _secure_redirect(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"


def _failed_callback_response() -> HTMLResponse:
    return HTMLResponse(
        "Microsoft connection could not be completed. Return to QQ and try again.",
        status.HTTP_400_BAD_REQUEST,
    )


def _authenticate(signer: OwnerSessionSigner, token: str) -> OwnerSession:
    try:
        session = signer.verify(token)
    except OwnerAuthenticationError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "owner authentication required") from exc
    if session.user_id != "owner":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "owner authentication required")
    return session


def _require_loopback_request(request: Request) -> None:
    if request.url.hostname not in {"127.0.0.1", "localhost"}:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")


def _set_loopback_cookie(response: Response, name: str, value: str, *, httponly: bool) -> None:
    response.set_cookie(
        name,
        value,
        max_age=900,
        secure=False,
        httponly=httponly,
        samesite="lax",
        path="/",
    )
