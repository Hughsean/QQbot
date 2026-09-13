"""Owner-bound Microsoft task capability grants."""

from uuid import UUID

from qq_time_agent.contracts.clock import Clock
from qq_time_agent.modules.connections.application.ports import (
    ConnectionRepository,
    MicrosoftConnectionProvider,
    OAuthProviderError,
)
from qq_time_agent.modules.connections.contracts import (
    TaskAccessError,
    TaskAccessGrant,
)
from qq_time_agent.modules.connections.domain.models import (
    ConnectionProvider,
    ConnectionStatus,
    ExternalConnection,
)
from qq_time_agent.modules.credentials.contracts import (
    CredentialHandle,
    CredentialKind,
    CredentialRef,
    CredentialVault,
)


class MicrosoftTaskAccessService:
    def __init__(
        self,
        repository: ConnectionRepository,
        vault: CredentialVault,
        provider: MicrosoftConnectionProvider,
        clock: Clock,
    ) -> None:
        self._repository = repository
        self._vault = vault
        self._provider = provider
        self._clock = clock

    async def acquire_task_access(self, user_id: str, connection_id: UUID) -> TaskAccessGrant:
        connection = await self._repository.get_for_user(connection_id, user_id)
        if connection is None or connection.provider is not ConnectionProvider.MICROSOFT:
            raise LookupError("Microsoft connection does not exist")
        if not connection.sync_enabled or connection.status not in {
            ConnectionStatus.ACTIVE,
            ConnectionStatus.DEGRADED,
        }:
            raise TaskAccessError("ConnectionUnavailable")
        if "Tasks.ReadWrite" not in connection.capabilities:
            raise TaskAccessError("Authorization")
        if connection.credential_ref is None or connection.provider_account_id is None:
            raise ValueError("connection task access is incomplete")
        credential = await self._refresh_access(connection)
        return TaskAccessGrant(
            connection.connection_id,
            connection.user_id,
            connection.provider_account_id,
            credential,
        )

    async def _refresh_access(self, connection: ExternalConnection) -> CredentialHandle:
        credential_ref = connection.credential_ref
        if credential_ref is None:
            raise ValueError("connection has no refresh credential")
        reference = CredentialRef(credential_ref)
        refresh_handle = await self._vault.open(reference)
        try:
            tokens = await self._provider.refresh_tasks(refresh_handle.reveal(self._clock.now()))
        except OAuthProviderError as exc:
            await self._record_failure(connection, exc.failure_class)
            raise TaskAccessError(exc.failure_class) from exc
        if tokens.refresh_token is not None:
            await self._vault.replace(reference, tokens.refresh_token.get_secret_value())
        return CredentialHandle(
            tokens.access_token.get_secret_value(), CredentialKind.ACCESS_TOKEN, tokens.expires_at
        )

    async def _record_failure(self, connection: ExternalConnection, failure_class: str) -> None:
        if failure_class == "Authentication":
            connection.require_reauthorization(self._clock.now())
        elif failure_class in {"TransientProvider", "RateLimit"}:
            connection.mark_degraded()
        else:
            return
        await self._repository.save(connection, connection.version - 1)
