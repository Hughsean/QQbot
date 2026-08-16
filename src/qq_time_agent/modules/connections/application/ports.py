"""Application ports for delegated OAuth and connection persistence."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from pydantic import SecretStr

from qq_time_agent.modules.connections.domain.models import ExternalConnection, OAuthTransaction


@dataclass(frozen=True, slots=True)
class ProviderAuthorization:
    authorization_url: str
    flow_state: SecretStr


@dataclass(frozen=True, slots=True)
class ProviderTokens:
    access_token: SecretStr
    refresh_token: SecretStr | None
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class ProviderProfile:
    account_id: str
    display_name: str | None
    email: str | None


class OAuthProviderError(RuntimeError):
    def __init__(self, failure_class: str) -> None:
        super().__init__(failure_class)
        self.failure_class = failure_class


class MicrosoftConnectionProvider(Protocol):
    async def begin_authorization(self, state: str) -> ProviderAuthorization: ...

    async def complete_authorization(
        self, flow_state: str, callback_parameters: dict[str, str]
    ) -> ProviderTokens: ...

    async def refresh(self, refresh_token: str) -> ProviderTokens: ...

    async def get_profile(self, access_token: str) -> ProviderProfile: ...


class ConnectionRepository(Protocol):
    async def add(self, connection: ExternalConnection) -> None: ...

    async def add_authorization(
        self, connection: ExternalConnection, transaction: OAuthTransaction
    ) -> None: ...

    async def claim_transaction(
        self, state_hash: bytes, browser_hash: bytes, now: datetime
    ) -> OAuthTransaction | None: ...

    async def get(self, connection_id: UUID) -> ExternalConnection | None: ...

    async def get_for_provider(self, user_id: str, provider: str) -> ExternalConnection | None: ...

    async def list_for_provider(
        self, user_id: str, provider: str
    ) -> tuple[ExternalConnection, ...]: ...

    async def get_for_user(
        self, connection_id: UUID, user_id: str
    ) -> ExternalConnection | None: ...

    async def get_by_identity(
        self, user_id: str, provider: str, fingerprint: str
    ) -> ExternalConnection | None: ...

    async def save(self, connection: ExternalConnection, expected_version: int) -> None: ...
