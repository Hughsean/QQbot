"""PostgreSQL AgentRun repository with Inbox-level idempotency."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from qq_time_agent.modules.agent.application.observation_codec import serialize_observation
from qq_time_agent.modules.agent.contracts import (
    AgentDelivery,
    AgentFinal,
    AgentRun,
    AgentRunClaim,
    AgentRunClaimError,
    AgentRunStatus,
    ContextScope,
    ConversationSnapshot,
    MailRunSummary,
    ToolObservation,
)
from qq_time_agent.modules.agent.infrastructure.conversation_event_builders import (
    build_agent_reply_event,
    build_tool_events,
)
from qq_time_agent.modules.agent.infrastructure.conversation_events import append_timeline_event
from qq_time_agent.modules.agent.infrastructure.scopes import SqlAgentContextScopes
from qq_time_agent.modules.agent.infrastructure.tables import (
    AgentRunRow,
    AgentToolCallRow,
)


class SqlAgentRunRepository(SqlAgentContextScopes):
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        super().__init__(sessions)

    async def list_recent_mail_summaries(
        self, user_id: str, since: datetime, limit: int = 20
    ) -> tuple[MailRunSummary, ...]:
        completed_at = func.coalesce(AgentRunRow.completed_at, AgentRunRow.updated_at)
        async with self._sessions() as session:
            rows = await session.scalars(
                select(AgentRunRow)
                .where(
                    AgentRunRow.user_id == user_id,
                    AgentRunRow.source_type.in_(("MICROSOFT_MAIL", "QQ_MAIL")),
                    AgentRunRow.status == AgentRunStatus.COMPLETED.value,
                    AgentRunRow.final_content.is_not(None),
                    completed_at >= since,
                )
                .order_by(completed_at.desc())
                .limit(max(1, min(limit, 20)))
            )
            return tuple(
                MailRunSummary(
                    row.run_id,
                    row.inbox_item_id,
                    row.source_type,
                    row.final_content or "",
                    row.completed_at or row.updated_at,
                )
                for row in rows
            )

    async def get_or_create(
        self,
        inbox_item_id: UUID,
        user_id: str,
        source_type: str,
        now: datetime,
        scope: ContextScope | None = None,
        source_refs: tuple[str, ...] = (),
    ) -> AgentRun:
        run_id = uuid4()
        values: dict[str, object] = {
            "run_id": run_id,
            "inbox_item_id": inbox_item_id,
            "user_id": user_id,
            "source_type": source_type,
            "status": AgentRunStatus.PENDING.value,
            "step": 0,
            "observations": [],
            "created_at": now,
            "updated_at": now,
            "version": 1,
            "conversation_id": None if scope is None else scope.conversation_id,
            "event_case_id": None if scope is None else scope.event_case_id,
            "source_refs": list(dict.fromkeys(source_refs)),
        }
        async with self._sessions.begin() as session:
            await session.execute(
                insert(AgentRunRow)
                .values(**values)
                .on_conflict_do_nothing(constraint="uq_agent_runs_inbox_item")
            )
            row = await session.scalar(
                select(AgentRunRow).where(AgentRunRow.inbox_item_id == inbox_item_id)
            )
            if row is None:
                raise RuntimeError("AgentRun idempotent insert lost stored row")
            return _to_run(row)

    async def get(self, run_id: UUID) -> AgentRun | None:
        async with self._sessions() as session:
            row = await session.get(AgentRunRow, run_id)
            return None if row is None else _to_run(row)

    async def save(self, run: AgentRun, expected_version: int) -> None:
        async with self._sessions.begin() as session:
            row = await session.get(AgentRunRow, run.run_id, with_for_update=True)
            if row is None or row.version != expected_version:
                raise RuntimeError("AgentRun version conflict")
            row.status = run.status.value
            row.step = run.step
            row.observations = run.observations
            row.final_content = run.final_content
            row.final_delivery = None if run.final_delivery is None else run.final_delivery.value
            row.effective_delivery = (
                None if run.effective_delivery is None else run.effective_delivery.value
            )
            row.failure_class = run.failure_class
            if run.updated_at is None:
                raise ValueError("AgentRun updated_at is required")
            row.updated_at = run.updated_at
            row.completed_at = run.completed_at
            row.context_revision = run.context_revision
            row.context_max_sequence = run.context_max_sequence
            row.context_hash = run.context_hash
            row.source_refs = list(run.source_refs)
            row.version = expected_version + 1

    async def record_context_snapshot(self, run_id: UUID, snapshot: ConversationSnapshot) -> None:
        """Pin the timeline read that produced this execution's context."""
        async with self._sessions.begin() as session:
            row = await session.get(AgentRunRow, run_id, with_for_update=True)
            if row is None:
                raise LookupError("AgentRun does not exist")
            if row.user_id != snapshot.user_id:
                raise ValueError("AgentRun context snapshot user does not match run")
            if row.conversation_id is not None and row.conversation_id != snapshot.scope_id:
                raise ValueError("AgentRun context snapshot scope does not match run")
            current = (row.context_revision, row.context_max_sequence, row.context_hash)
            incoming = (snapshot.revision, snapshot.max_sequence, snapshot.context_hash)
            if any(value is not None for value in current):
                if current != incoming:
                    raise ValueError("AgentRun context snapshot is already pinned")
                return
            row.context_revision, row.context_max_sequence, row.context_hash = incoming
            row.version += 1

    async def freeze_effective_delivery(
        self, run_id: UUID, delivery: AgentDelivery
    ) -> AgentDelivery:
        async with self._sessions.begin() as session:
            row = await session.get(AgentRunRow, run_id, with_for_update=True)
            if row is None:
                raise LookupError("AgentRun does not exist")
            if row.status != AgentRunStatus.COMPLETED.value:
                raise ValueError("AgentRun delivery can only be frozen after completion")
            if row.effective_delivery is None:
                row.effective_delivery = delivery.value
            return AgentDelivery(row.effective_delivery)

    async def claim(
        self,
        run_id: UUID,
        execution_owner: str,
        now: datetime,
        lease_until: datetime,
    ) -> AgentRunClaim | None:
        if not execution_owner.strip() or lease_until <= now:
            raise ValueError("AgentRun claim owner and future lease are required")
        async with self._sessions.begin() as session:
            row = await session.get(AgentRunRow, run_id, with_for_update=True)
            if row is None:
                raise LookupError("AgentRun does not exist")
            if row.status == AgentRunStatus.COMPLETED.value:
                return None
            if (
                row.status == AgentRunStatus.RUNNING.value
                and row.execution_lease_until is not None
                and row.execution_lease_until >= now
            ):
                return None
            row.status = AgentRunStatus.RUNNING.value
            row.execution_owner = execution_owner
            row.execution_lease_until = lease_until
            row.execution_epoch += 1
            row.failure_class = None
            row.updated_at = now
            row.version += 1
            await session.flush()
            return _to_claim(row)

    async def renew_claim(
        self,
        claim: AgentRunClaim,
        now: datetime,
        lease_until: datetime,
    ) -> AgentRunClaim:
        if lease_until <= now:
            raise ValueError("AgentRun renewal must extend into the future")
        async with self._sessions.begin() as session:
            row = await _owned_row(session, claim, now)
            row.execution_lease_until = lease_until
            row.updated_at = now
            row.version += 1
            await session.flush()
            return _to_claim(row)

    async def checkpoint_claimed_tool_call(
        self,
        claim: AgentRunClaim,
        observation: ToolObservation,
        now: datetime,
    ) -> AgentRunClaim:
        async with self._sessions.begin() as session:
            run = await _owned_row(session, claim, now)
            serialized = serialize_observation(observation)
            if not any(value.get("call_id") == observation.call_id for value in run.observations):
                run.observations = [*run.observations, serialized]
                run.step = len(run.observations)
                run.updated_at = now
                run.version += 1
                await _insert_tool_call(session, run.run_id, observation, serialized, now)
                for event in build_tool_events(run, observation, now):
                    await append_timeline_event(session, event, now)
            await session.flush()
            return _to_claim(run)

    async def complete_claim(
        self,
        claim: AgentRunClaim,
        result: AgentFinal,
        now: datetime,
    ) -> AgentRun:
        async with self._sessions.begin() as session:
            row = await _owned_row(session, claim, now)
            row.status = AgentRunStatus.COMPLETED.value
            row.final_content = result.content[:12000]
            row.final_delivery = result.delivery.value
            row.failure_class = None
            row.execution_owner = None
            row.execution_lease_until = None
            row.updated_at = now
            row.completed_at = now
            row.version += 1
            await session.flush()
            reply_event = build_agent_reply_event(row, result.delivery.value, now)
            if reply_event is not None:
                await append_timeline_event(session, reply_event, now)
            return _to_run(row)

    async def fail_claim(
        self,
        claim: AgentRunClaim,
        failure_class: str,
        now: datetime,
    ) -> AgentRun:
        async with self._sessions.begin() as session:
            row = await _owned_row(session, claim, now)
            row.status = AgentRunStatus.FAILED.value
            row.failure_class = failure_class[:120]
            row.execution_owner = None
            row.execution_lease_until = None
            row.updated_at = now
            row.version += 1
            await session.flush()
            return _to_run(row)

    async def fail_unclaimed(self, run_id: UUID, failure_class: str, now: datetime) -> AgentRun:
        async with self._sessions.begin() as session:
            row = await session.get(AgentRunRow, run_id, with_for_update=True)
            if row is None:
                raise LookupError("AgentRun does not exist")
            if row.status == AgentRunStatus.COMPLETED.value:
                return _to_run(row)
            if (
                row.status == AgentRunStatus.RUNNING.value
                and row.execution_lease_until is not None
                and row.execution_lease_until >= now
            ):
                raise AgentRunClaimError("AgentRun is already claimed")
            row.status = AgentRunStatus.FAILED.value
            row.failure_class = failure_class[:120]
            row.execution_owner = None
            row.execution_lease_until = None
            row.updated_at = now
            row.version += 1
            await session.flush()
            return _to_run(row)

    async def checkpoint_tool_call(
        self,
        run_id: UUID,
        observation: ToolObservation,
        now: datetime,
    ) -> None:
        async with self._sessions.begin() as session:
            run = await session.get(AgentRunRow, run_id, with_for_update=True)
            if run is None:
                raise LookupError("AgentRun does not exist")
            serialized = serialize_observation(observation)
            if any(value.get("call_id") == observation.call_id for value in run.observations):
                return
            run.observations = [*run.observations, serialized]
            run.step = len(run.observations)
            run.updated_at = now
            run.version += 1
            await _insert_tool_call(session, run_id, observation, serialized, now)
            for event in build_tool_events(run, observation, now):
                await append_timeline_event(session, event, now)


def _to_run(row: AgentRunRow) -> AgentRun:
    return AgentRun(
        row.run_id,
        row.inbox_item_id,
        row.user_id,
        row.source_type,
        AgentRunStatus(row.status),
        row.step,
        list(row.observations),
        row.final_content,
        None if row.final_delivery is None else AgentDelivery(row.final_delivery),
        row.failure_class,
        row.created_at,
        row.updated_at,
        row.version,
        row.conversation_id,
        row.event_case_id,
        row.execution_owner,
        row.execution_lease_until,
        row.execution_epoch,
        None if row.effective_delivery is None else AgentDelivery(row.effective_delivery),
        row.completed_at,
        row.context_revision,
        row.context_max_sequence,
        row.context_hash,
        tuple(row.source_refs),
    )


def _to_claim(row: AgentRunRow) -> AgentRunClaim:
    if row.execution_owner is None or row.execution_lease_until is None:
        raise RuntimeError("AgentRun claim row is incomplete")
    return AgentRunClaim(
        _to_run(row),
        row.execution_owner,
        row.execution_epoch,
        row.execution_lease_until,
    )


async def _owned_row(
    session: AsyncSession,
    claim: AgentRunClaim,
    now: datetime,
) -> AgentRunRow:
    row = await session.get(AgentRunRow, claim.run.run_id, with_for_update=True)
    if (
        row is None
        or row.status != AgentRunStatus.RUNNING.value
        or row.execution_owner != claim.execution_owner
        or row.execution_epoch != claim.execution_epoch
        or row.execution_lease_until is None
        or row.execution_lease_until < now
    ):
        raise AgentRunClaimError("AgentRun execution claim is stale or lost")
    return row


async def _insert_tool_call(
    session: AsyncSession,
    run_id: UUID,
    observation: ToolObservation,
    serialized: dict[str, object],
    now: datetime,
) -> None:
    await session.execute(
        insert(AgentToolCallRow)
        .values(
            run_id=run_id,
            call_id=observation.call_id,
            tool_name=observation.name,
            arguments_hash=observation.arguments_hash,
            observation=serialized,
            created_at=now,
        )
        .on_conflict_do_nothing()
    )
