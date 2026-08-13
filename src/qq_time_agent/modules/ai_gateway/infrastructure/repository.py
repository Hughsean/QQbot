"""PostgreSQL AI invocation metadata repository."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from qq_time_agent.modules.ai_gateway.application.ports import InvocationMetadata
from qq_time_agent.modules.ai_gateway.infrastructure.tables import ModelInvocationRow


class SqlInvocationRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def add(self, value: InvocationMetadata) -> None:
        async with self._sessions.begin() as session:
            session.add(
                ModelInvocationRow(
                    invocation_id=value.invocation_id,
                    use_case=value.use_case,
                    prompt_version=value.prompt_version,
                    route=value.route,
                    model=value.model,
                    status=value.status,
                    failure_class=value.failure_class,
                    input_tokens=value.input_tokens,
                    output_tokens=value.output_tokens,
                    started_at=value.started_at,
                    completed_at=value.completed_at,
                    latency_ms=value.latency_ms,
                )
            )
