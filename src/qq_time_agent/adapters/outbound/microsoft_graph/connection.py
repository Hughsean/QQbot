"""MSAL/Graph containment with bounded calls and provider-neutral mapping."""

import asyncio
import json
from collections.abc import Callable
from datetime import timedelta
from typing import Any, Protocol, cast

import httpx
import msal  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, SecretStr, ValidationError

from qq_time_agent.bootstrap.config_models import MicrosoftConfig
from qq_time_agent.contracts.clock import Clock
from qq_time_agent.modules.connections.application.ports import (
    OAuthProviderError,
    ProviderAuthorization,
    ProviderProfile,
    ProviderTokens,
)

SCOPES = ["User.Read", "Mail.Read", "email"]


class _SyncHttpClient:
    def __init__(self, timeout_seconds: float) -> None:
        self._client = httpx.Client(timeout=timeout_seconds, follow_redirects=False)

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return self._client.get(url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return self._client.post(url, **kwargs)


class _MsalApplication(Protocol):
    def initiate_auth_code_flow(self, scopes: list[str], **kwargs: object) -> dict[str, object]: ...

    def acquire_token_by_auth_code_flow(
        self, flow: dict[str, object], response: dict[str, str], **kwargs: object
    ) -> dict[str, object]: ...

    def acquire_token_by_refresh_token(
        self, refresh_token: str, scopes: list[str], **kwargs: object
    ) -> dict[str, object]: ...


class _TokenResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    access_token: SecretStr
    refresh_token: SecretStr | None = None
    expires_in: int


class _GraphProfile(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    account_id: str
    display_name: str | None = None
    mail: str | None = None
    user_principal_name: str | None = None


class MicrosoftGraphConnectionAdapter:
    def __init__(
        self,
        config: MicrosoftConfig,
        clock: Clock,
        async_client: httpx.AsyncClient | None = None,
        application_factory: Callable[[], _MsalApplication] | None = None,
        timeout_seconds: float = 15.0,
        max_attempts: int = 2,
    ) -> None:
        self._config = config
        self._clock = clock
        self._client = async_client or httpx.AsyncClient(
            base_url="https://graph.microsoft.com", timeout=timeout_seconds
        )
        self._owns_client = async_client is None
        self._application_factory = application_factory or self._new_application
        self._timeout_seconds = timeout_seconds
        self._max_attempts = max_attempts

    async def begin_authorization(self, state: str) -> ProviderAuthorization:
        if not state:
            raise ValueError("OAuth state is required")

        def begin() -> dict[str, object]:
            return self._application_factory().initiate_auth_code_flow(
                SCOPES,
                redirect_uri=self._config.redirect_uri,
                state=state,
                response_mode="query",
            )

        flow = await self._run_sync(begin)
        auth_uri = flow.get("auth_uri")
        if not isinstance(auth_uri, str) or not auth_uri.startswith("https://"):
            raise OAuthProviderError("PermanentProvider")
        return ProviderAuthorization(auth_uri, SecretStr(json.dumps(flow, separators=(",", ":"))))

    async def complete_authorization(
        self, flow_state: str, callback_parameters: dict[str, str]
    ) -> ProviderTokens:
        try:
            flow = cast("dict[str, object]", json.loads(flow_state))
        except (TypeError, ValueError) as exc:
            raise OAuthProviderError("SecurityPolicy") from exc

        def complete() -> dict[str, object]:
            return self._application_factory().acquire_token_by_auth_code_flow(
                flow, callback_parameters, scopes=SCOPES
            )

        return self._tokens(await self._run_sync(complete))

    async def refresh(self, refresh_token: str) -> ProviderTokens:
        if not refresh_token:
            raise ValueError("refresh token is required")

        def refresh_token_call() -> dict[str, object]:
            return self._application_factory().acquire_token_by_refresh_token(refresh_token, SCOPES)

        return self._tokens(await self._run_sync(refresh_token_call))

    async def get_profile(self, access_token: str) -> ProviderProfile:
        response = await self._graph_get(
            "/v1.0/me",
            access_token,
            {"$select": "id,displayName,mail,userPrincipalName"},
        )
        try:
            payload = response.json()
            profile = _GraphProfile.model_validate(
                {
                    "account_id": payload.get("id"),
                    "display_name": payload.get("displayName"),
                    "mail": payload.get("mail"),
                    "user_principal_name": payload.get("userPrincipalName"),
                }
            )
        except (ValueError, ValidationError, AttributeError) as exc:
            raise OAuthProviderError("PermanentProvider") from exc
        return ProviderProfile(
            profile.account_id,
            profile.display_name,
            profile.mail or profile.user_principal_name,
        )

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _new_application(self) -> _MsalApplication:
        authority = f"https://login.microsoftonline.com/{self._config.tenant}"
        return cast(
            "_MsalApplication",
            msal.ConfidentialClientApplication(
                self._config.client_id.get_secret_value(),
                authority=authority,
                client_credential=self._config.client_secret.get_secret_value(),
                http_client=_SyncHttpClient(self._timeout_seconds),
            ),
        )

    async def _run_sync(self, operation: Callable[[], dict[str, object]]) -> dict[str, object]:
        for attempt in range(self._max_attempts):
            try:
                return await asyncio.wait_for(
                    asyncio.to_thread(operation), self._timeout_seconds + 1
                )
            except (httpx.NetworkError, httpx.TimeoutException, TimeoutError) as exc:
                if attempt + 1 == self._max_attempts:
                    raise OAuthProviderError("TransientProvider") from exc
                await asyncio.sleep(0.1 * (attempt + 1))
            except ValueError as exc:
                raise OAuthProviderError("SecurityPolicy") from exc
        raise AssertionError("unreachable")

    def _tokens(self, result: dict[str, object]) -> ProviderTokens:
        if "error" in result:
            raise OAuthProviderError(_classify_oauth_error(str(result.get("error"))))
        try:
            response = _TokenResponse.model_validate(result)
        except ValidationError as exc:
            raise OAuthProviderError("PermanentProvider") from exc
        return ProviderTokens(
            response.access_token,
            response.refresh_token,
            self._clock.now() + timedelta(seconds=response.expires_in),
        )

    async def _graph_get(
        self, path: str, access_token: str, params: dict[str, str]
    ) -> httpx.Response:
        for attempt in range(self._max_attempts):
            try:
                response = await self._client.get(
                    path,
                    headers={"Authorization": f"Bearer {access_token}"},
                    params=params,
                )
            except (httpx.NetworkError, httpx.TimeoutException) as exc:
                if attempt + 1 == self._max_attempts:
                    raise OAuthProviderError("TransientProvider") from exc
                await asyncio.sleep(0.1 * (attempt + 1))
                continue
            failure = _classify_graph_status(response.status_code)
            if failure is None:
                return response
            if failure in {"RateLimit", "TransientProvider"} and attempt + 1 < self._max_attempts:
                await asyncio.sleep(0.1 * (attempt + 1))
                continue
            raise OAuthProviderError(failure)
        raise AssertionError("unreachable")


def _classify_oauth_error(error: str) -> str:
    if error in {"invalid_grant", "interaction_required", "login_required"}:
        return "Authentication"
    if error in {"access_denied", "unauthorized_client"}:
        return "Authorization"
    if error in {"temporarily_unavailable", "server_error"}:
        return "TransientProvider"
    return "PermanentProvider"


def _classify_graph_status(status: int) -> str | None:
    if 200 <= status < 300:
        return None
    if status == 401:
        return "Authentication"
    if status == 403:
        return "Authorization"
    if status == 429:
        return "RateLimit"
    if status >= 500:
        return "TransientProvider"
    return "PermanentProvider"
