"""Credential-free reauthorization reminder query."""

from uuid import UUID

from qq_time_agent.modules.connections.application.ports import ConnectionRepository
from qq_time_agent.modules.connections.contracts import ReauthReminderCandidate
from qq_time_agent.modules.connections.domain.models import (
    ConnectionProvider,
    ConnectionStatus,
    ExternalConnection,
)


class ConnectionNotificationQueryService:
    def __init__(self, repository: ConnectionRepository) -> None:
        self._repository = repository

    async def is_reauth_episode(self, user_id: str, connection_id: UUID, reauth_epoch: int) -> bool:
        value = await self._repository.get_for_user(connection_id, user_id)
        return bool(
            value is not None
            and value.status is ConnectionStatus.REAUTH_REQUIRED
            and value.reauth_epoch == reauth_epoch
            and value.reauth_required_since is not None
        )

    async def list_reauth_required(self, user_id: str) -> tuple[ReauthReminderCandidate, ...]:
        values: list[ExternalConnection] = []
        for provider in ConnectionProvider:
            values.extend(await self._repository.list_for_provider(user_id, provider.value))
        return tuple(
            ReauthReminderCandidate(
                value.connection_id,
                value.provider.value,
                value.display_label,
                value.reauth_epoch,
                value.reauth_required_since,
            )
            for value in values
            if value.status is ConnectionStatus.REAUTH_REQUIRED
            and value.reauth_required_since is not None
        )
