"""Verified Microsoft account identity binding policy."""

from qq_time_agent.modules.connections.application.identity import AccountFingerprinter
from qq_time_agent.modules.connections.application.oauth_values import mask_account
from qq_time_agent.modules.connections.application.ports import (
    ConnectionRepository,
    ProviderProfile,
)
from qq_time_agent.modules.connections.domain.models import (
    ConnectionProvider,
    ConnectionStatus,
    ExternalConnection,
)


async def bind_microsoft_identity(
    repository: ConnectionRepository,
    fingerprinter: AccountFingerprinter,
    connection: ExternalConnection,
    profile: ProviderProfile,
) -> None:
    fingerprint = fingerprinter.fingerprint(
        ConnectionProvider.MICROSOFT.value, profile.account_id.lower()
    )
    duplicate = await repository.get_by_identity(
        connection.user_id, ConnectionProvider.MICROSOFT.value, fingerprint
    )
    if duplicate is not None and duplicate.connection_id != connection.connection_id:
        raise ValueError("Microsoft account is already connected")
    values = await repository.list_for_provider(
        connection.user_id, ConnectionProvider.MICROSOFT.value
    )
    connection.bind_identity(
        fingerprint,
        mask_account(profile.email),
        is_default=connection.is_default or not _has_default(values),
    )


def _has_default(values: tuple[ExternalConnection, ...]) -> bool:
    return any(
        value.is_default and value.status is not ConnectionStatus.DISCONNECTED for value in values
    )
