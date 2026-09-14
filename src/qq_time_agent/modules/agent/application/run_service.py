"""Durable execution boundary for owner and mail Agent runs."""

from collections.abc import Mapping
from contextlib import suppress
from datetime import datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

from qq_time_agent.contracts.clock import Clock
from qq_time_agent.modules.agent.application.loop import AgentLoop
from qq_time_agent.modules.agent.application.observation_codec import deserialize_observation
from qq_time_agent.modules.agent.contracts import (
    AgentContextRepository,
    AgentDelivery,
    AgentFinal,
    AgentRun,
    AgentRunClaimError,
    AgentRunEvent,
    AgentRunEventRepository,
    AgentRunEventType,
    AgentRunExecution,
    AgentRunExecutionStatus,
    AgentRunRepository,
    AgentRunStatus,
    ConversationEvent,
    ConversationEventRepository,
    ConversationEventType,
    ConversationScopeType,
    ConversationSnapshot,
    ToolObservation,
    bounded_event_content,
)
from qq_time_agent.modules.ai_gateway.contracts import AgentMessage


class AgentRunService:
    def __init__(
        self,
        repository: AgentRunRepository,
        loop: AgentLoop,
        clock: Clock,
        events: AgentRunEventRepository | None = None,
        execution_lease: timedelta = timedelta(minutes=5),
        timeline: ConversationEventRepository | None = None,
    ) -> None:
        if execution_lease <= timedelta(0):
            raise ValueError("AgentRun execution lease must be positive")
        self._repository = repository
        self._loop = loop
        self._clock = clock
        self._execution_lease = execution_lease
        self._context_repository: AgentContextRepository | None = (
            cast(AgentContextRepository, repository)
            if hasattr(repository, "ensure_scope")
            else None
        )
        self._events = events
        self._timeline = timeline

    async def ensure_run(
        self,
        inbox_item_id: UUID,
        user_id: str,
        source_type: str,
        conversation_key: str | None = None,
        event_key: str | None = None,
        occurred_at: datetime | None = None,
        message: str | None = None,
        source_refs: tuple[str, ...] = (),
    ) -> AgentRun:
        scope = None
        timestamp = occurred_at or self._clock.now()
        if self._context_repository is not None and (conversation_key or event_key):
            scope = await self._context_repository.ensure_scope(
                user_id, conversation_key, event_key, timestamp
            )
            await self._context_repository.attach_item(scope, inbox_item_id, timestamp)
        run = await self._repository.get_or_create(
            inbox_item_id,
            user_id,
            source_type,
            self._clock.now(),
            scope,
            source_refs,
        )
        await self._record_user_message(scope, run, message, source_type, timestamp)
        return run

    async def _record_user_message(
        self,
        scope: object,
        run: AgentRun,
        message: str | None,
        source_type: str,
        occurred_at: datetime,
    ) -> None:
        conversation_id = getattr(scope, "conversation_id", None) or run.conversation_id
        if (
            self._timeline is None
            or message is None
            or not message.strip()
            or conversation_id is None
        ):
            return
        event = ConversationEvent(
            scope_type=ConversationScopeType.CONVERSATION,
            scope_id=conversation_id,
            user_id=run.user_id,
            event_type=ConversationEventType.USER_MESSAGE,
            occurred_at=occurred_at,
            content=bounded_event_content(message),
            idempotency_key=f"user-message:{run.inbox_item_id}",
            inbox_item_id=run.inbox_item_id,
            content_ref=f"inbox:{run.inbox_item_id}",
            metadata={"source_type": source_type},
        )
        with suppress(Exception):
            await self._timeline.append(event, self._clock.now())

    async def get(self, run_id: UUID) -> AgentRun | None:
        return await self._repository.get(run_id)

    async def freeze_effective_delivery(
        self, run_id: UUID, delivery: AgentDelivery
    ) -> AgentDelivery:
        return await self._repository.freeze_effective_delivery(run_id, delivery)

    async def fail_before_execution(self, run_id: UUID, failure_class: str) -> None:
        await self._repository.fail_unclaimed(run_id, failure_class, self._clock.now())

    async def execute(  # noqa: C901
        self,
        run_id: UUID,
        message: str,
        context: str = "",
        timeline_messages: tuple[AgentMessage, ...] = (),
        snapshot: ConversationSnapshot | None = None,
    ) -> AgentRunExecution:
        run = await self._repository.get(run_id)
        if run is None:
            raise LookupError("AgentRun does not exist")
        completed = _completed_final(run)
        if completed is not None:
            return AgentRunExecution(AgentRunExecutionStatus.COMPLETED, completed)
        if not hasattr(self._repository, "claim"):
            return await self._execute_legacy(
                run, run_id, message, context, timeline_messages, snapshot
            )

        now = self._clock.now()
        execution_owner = f"agent-run:{uuid4().hex}"
        claim = await self._repository.claim(
            run_id, execution_owner, now, now + self._execution_lease
        )
        if claim is None:
            current = await self._repository.get(run_id)
            if current is None:
                raise RuntimeError("AgentRun disappeared while claiming execution")
            completed = _completed_final(current)
            if completed is not None:
                return AgentRunExecution(AgentRunExecutionStatus.COMPLETED, completed)
            return AgentRunExecution(AgentRunExecutionStatus.IN_PROGRESS)

        try:
            _validate_snapshot(claim.run, snapshot)
            if snapshot is not None and not _has_snapshot(claim.run):
                await self._record_snapshot(run_id, snapshot)
        except AgentRunClaimError:
            return AgentRunExecution(AgentRunExecutionStatus.IN_PROGRESS)
        except Exception as exc:
            with suppress(AgentRunClaimError):
                await self._repository.fail_claim(claim, type(exc).__name__, self._clock.now())
            raise
        if self._events is not None:
            with suppress(Exception):
                await self._events.append(
                    AgentRunEvent(
                        run_id,
                        AgentRunEventType.RUN_CLAIMED,
                        now,
                        metadata={"execution_epoch": claim.execution_epoch},
                        idempotency_key=f"{run_id}:claimed:{claim.execution_epoch}",
                    )
                )

        async def record_event(event_type: str, step: int, metadata: Mapping[str, object]) -> None:
            if self._events is not None:
                with suppress(Exception):
                    await self._events.append(
                        AgentRunEvent(
                            run_id,
                            AgentRunEventType(event_type),
                            self._clock.now(),
                            step=step,
                            metadata=metadata,
                            idempotency_key=f"{run_id}:{event_type}:{step}:{hash(tuple(sorted(metadata.items())))}",
                        )
                    )

        async def renew() -> None:
            nonlocal claim
            assert claim is not None
            renewed_at = self._clock.now()
            claim = await self._repository.renew_claim(
                claim, renewed_at, renewed_at + self._execution_lease
            )

        async def record(observation: ToolObservation) -> None:
            nonlocal claim
            assert claim is not None
            claim = await self._repository.checkpoint_claimed_tool_call(
                claim, observation, self._clock.now()
            )

        try:
            result = await self._loop.run(
                claim.run.user_id,
                message,
                context,
                timeline_messages,
                _observations(claim.run.observations),
                record,
                renew,
                record_event,
                source_type=claim.run.source_type,
                inbox_item_id=claim.run.inbox_item_id,
                source_refs=claim.run.source_refs,
            )
            await renew()
            await self._repository.complete_claim(claim, result, self._clock.now())
        except AgentRunClaimError:
            return AgentRunExecution(AgentRunExecutionStatus.IN_PROGRESS)
        except Exception as exc:
            with suppress(AgentRunClaimError):
                await self._repository.fail_claim(claim, type(exc).__name__, self._clock.now())
            raise
        return AgentRunExecution(AgentRunExecutionStatus.EXECUTED, result)

    async def _record_snapshot(self, run_id: UUID, snapshot: ConversationSnapshot | None) -> None:
        """Persist the pinned context snapshot as execution metadata."""
        if snapshot is None:
            return
        recorder = getattr(self._repository, "record_context_snapshot", None)
        if recorder is None:
            raise RuntimeError("AgentRun repository cannot persist context snapshot")
        await recorder(run_id, snapshot)

    async def _execute_legacy(
        self,
        run: AgentRun,
        run_id: UUID,
        message: str,
        context: str,
        timeline_messages: tuple[AgentMessage, ...],
        snapshot: ConversationSnapshot | None,
    ) -> AgentRunExecution:
        expected_version = run.version
        run.status = AgentRunStatus.RUNNING
        run.updated_at = self._clock.now()
        _pin_snapshot(run, snapshot)
        await self._repository.save(run, expected_version)

        async def record(observation: ToolObservation) -> None:
            await self._repository.checkpoint_tool_call(run_id, observation, self._clock.now())

        try:
            result = await self._loop.run(
                run.user_id,
                message,
                context,
                timeline_messages,
                _observations(run.observations),
                record,
                source_type=run.source_type,
                inbox_item_id=run.inbox_item_id,
                source_refs=run.source_refs,
            )
        except Exception as exc:
            current = await self._repository.get(run_id)
            if current is not None:
                current.status = AgentRunStatus.FAILED
                current.failure_class = type(exc).__name__
                current.updated_at = self._clock.now()
                await self._repository.save(current, current.version)
            raise
        current = await self._repository.get(run_id)
        if current is None:
            raise RuntimeError("AgentRun disappeared during execution")
        finished_at = self._clock.now()
        current.status = AgentRunStatus.COMPLETED
        current.final_content = result.content[:12000]
        current.final_delivery = result.delivery
        current.updated_at = finished_at
        current.completed_at = finished_at
        await self._repository.save(current, current.version)
        return AgentRunExecution(AgentRunExecutionStatus.EXECUTED, result)


def _pin_snapshot(run: AgentRun, snapshot: ConversationSnapshot | None) -> None:
    _validate_snapshot(run, snapshot)
    if snapshot is None:
        return
    current = (run.context_revision, run.context_max_sequence, run.context_hash)
    incoming = (snapshot.revision, snapshot.max_sequence, snapshot.context_hash)
    if any(value is not None for value in current):
        if current != incoming:
            raise ValueError("AgentRun context snapshot is already pinned")
        return
    run.context_revision, run.context_max_sequence, run.context_hash = incoming


def _has_snapshot(run: AgentRun) -> bool:
    return all(
        value is not None
        for value in (run.context_revision, run.context_max_sequence, run.context_hash)
    )


def _validate_snapshot(run: AgentRun, snapshot: ConversationSnapshot | None) -> None:
    if snapshot is None:
        return
    if snapshot.user_id != run.user_id:
        raise ValueError("AgentRun context snapshot user does not match run")
    if run.conversation_id is not None and snapshot.scope_id != run.conversation_id:
        raise ValueError("AgentRun context snapshot scope does not match run")
    current = (run.context_revision, run.context_max_sequence, run.context_hash)
    if any(value is not None for value in current) and current != (
        snapshot.revision,
        snapshot.max_sequence,
        snapshot.context_hash,
    ):
        raise ValueError("AgentRun context snapshot is already pinned")


def _completed_final(run: AgentRun) -> AgentFinal | None:
    if run.status is not AgentRunStatus.COMPLETED:
        return None
    if run.final_content is None or run.final_delivery is None:
        raise ValueError("Completed AgentRun is missing its persisted final response")
    return AgentFinal(run.final_content, run.final_delivery)


def _observations(values: list[dict[str, object]]) -> tuple[ToolObservation, ...]:
    return tuple(
        observation
        for value in values
        if (observation := deserialize_observation(value)) is not None
    )
