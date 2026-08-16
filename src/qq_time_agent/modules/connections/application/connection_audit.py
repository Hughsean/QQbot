"""Privacy-safe audit emission for external connection lifecycle events."""

from qq_time_agent.contracts.clock import Clock
from qq_time_agent.modules.audit.contracts import AuditEvent, AuditPort
from qq_time_agent.modules.connections.domain.models import ExternalConnection


async def append_connection_audit(
    audit: AuditPort | None,
    clock: Clock,
    connection: ExternalConnection,
    event_type: str,
) -> None:
    if audit is None:
        return
    await audit.append(
        AuditEvent(
            event_type,
            connection.user_id,
            f"connection:{connection.connection_id}",
            connection.status.value,
            clock.now(),
            {"provider": connection.provider.value},
        )
    )
