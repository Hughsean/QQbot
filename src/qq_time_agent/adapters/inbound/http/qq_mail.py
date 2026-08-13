"""Loopback-only owner HTTP surface for QQ Mail connections."""

import secrets
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Cookie, Header, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, SecretStr

from qq_time_agent.adapters.inbound.http.microsoft_oauth import (
    CSRF_COOKIE,
    OWNER_COOKIE,
    _authenticate,
    _owner_start_page,
    _require_loopback_request,
    _set_loopback_cookie,
)
from qq_time_agent.adapters.inbound.http.owner_session import (
    OwnerAuthenticationError,
    OwnerSessionSigner,
    verify_csrf,
)
from qq_time_agent.modules.connections.application.qq_mail import (
    QqMailConnectCommand,
    QqMailConnectionService,
)
from qq_time_agent.modules.connections.contracts import ConnectionStatusView
from qq_time_agent.modules.inbox.contracts import MailProviderError


class QqMailConnectRequest(BaseModel):
    address: str
    authorization_code: SecretStr


class QqMailDisconnectRequest(BaseModel):
    connection_id: UUID
    confirmed: bool


def qq_mail_router(service: QqMailConnectionService, signer: OwnerSessionSigner) -> APIRouter:
    router = APIRouter()

    @router.get("/qq-mail/owner-start", response_class=HTMLResponse)
    async def owner_start(request: Request) -> HTMLResponse:
        _require_loopback_request(request)
        token = signer.issue("owner")
        nonce = secrets.token_urlsafe(18)
        response = HTMLResponse(
            _owner_start_page("/api/v1/owner/session", token, nonce, "/qq-mail/connect")
        )
        _secure_page(response, nonce)
        return response

    @router.get("/qq-mail/connect", response_class=HTMLResponse)
    async def connect_page(
        request: Request,
        owner_cookie: Annotated[str | None, Cookie(alias=OWNER_COOKIE)] = None,
    ) -> HTMLResponse:
        _require_loopback_request(request)
        _authenticate(signer, owner_cookie or "")
        csrf = secrets.token_urlsafe(24)
        nonce = secrets.token_urlsafe(18)
        response = HTMLResponse(_connect_page(csrf, nonce))
        _set_loopback_cookie(response, CSRF_COOKIE, csrf, httponly=False)
        _secure_page(response, nonce)
        return response

    @router.post("/api/v1/connections/qq-mail", response_model=ConnectionStatusView)
    async def connect(
        request: Request,
        payload: QqMailConnectRequest,
        owner_cookie: Annotated[str | None, Cookie(alias=OWNER_COOKIE)] = None,
        csrf_cookie: Annotated[str | None, Cookie(alias=CSRF_COOKIE)] = None,
        csrf_header: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
    ) -> ConnectionStatusView:
        _require_loopback_request(request)
        owner = _authenticate(signer, owner_cookie or "")
        _check_csrf(csrf_cookie, csrf_header)
        try:
            return await service.connect(
                QqMailConnectCommand(owner.user_id, payload.address, payload.authorization_code)
            )
        except MailProviderError as exc:
            code = status.HTTP_401_UNAUTHORIZED if exc.failure_class == "Authentication" else 503
            raise HTTPException(code, "QQ Mail verification failed") from None
        except ValueError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None

    @router.get("/api/v1/connections/qq-mail/status", response_model=ConnectionStatusView | None)
    async def connection_status(
        request: Request,
        owner_cookie: Annotated[str | None, Cookie(alias=OWNER_COOKIE)] = None,
    ) -> ConnectionStatusView | None:
        _require_loopback_request(request)
        owner = _authenticate(signer, owner_cookie or "")
        return await service.status(owner.user_id)

    @router.post("/api/v1/connections/qq-mail/disconnect", response_model=ConnectionStatusView)
    async def disconnect(
        request: Request,
        payload: QqMailDisconnectRequest,
        owner_cookie: Annotated[str | None, Cookie(alias=OWNER_COOKIE)] = None,
        csrf_cookie: Annotated[str | None, Cookie(alias=CSRF_COOKIE)] = None,
        csrf_header: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
    ) -> ConnectionStatusView:
        _require_loopback_request(request)
        _authenticate(signer, owner_cookie or "")
        _check_csrf(csrf_cookie, csrf_header)
        if not payload.confirmed:
            raise HTTPException(status.HTTP_409_CONFLICT, "disconnect requires confirmation")
        return await service.disconnect(payload.connection_id)

    return router


def _check_csrf(cookie: str | None, header: str | None) -> None:
    try:
        verify_csrf(cookie, header)
    except OwnerAuthenticationError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "request verification failed") from exc


def _secure_page(response: HTMLResponse, nonce: str) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = (
        f"default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-{nonce}'; "
        "connect-src 'self'; form-action 'self'; base-uri 'none'"
    )


def _connect_page(csrf: str, nonce: str) -> str:
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>连接 QQ 邮箱</title><style>body{{font-family:system-ui;max-width:36rem;margin:4rem auto}}
label,input,button{{display:block;width:100%;margin:.7rem 0;padding:.6rem}}</style></head><body>
<h1>连接 QQ 邮箱</h1><p>请输入完整邮箱地址和 QQ 邮箱生成的 IMAP 授权码。</p>
<form><label>QQ 邮箱<input name="address" type="email" required></label>
<label>IMAP 授权码<input name="code" type="password" required></label>
<button>验证并连接</button></form><p id="result"></p><script nonce="{nonce}">
document.forms[0].onsubmit=async(e)=>{{e.preventDefault();let f=new FormData(e.target);
let h={{'Content-Type':'application/json','X-CSRF-Token':'{csrf}'}};
let b=JSON.stringify({{address:f.get('address'),authorization_code:f.get('code')}});
let r=await fetch('/api/v1/connections/qq-mail',{{method:'POST',headers:h,body:b}});
document.getElementById('result').textContent=r.ok?'连接成功, 可以关闭此页面。':
'连接失败, 请检查邮箱地址和授权码。';}};</script></body></html>"""
