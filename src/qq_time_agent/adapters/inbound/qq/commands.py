"""Owner-only QQ ingress routing with persistent AgentRun execution."""

import logging
from contextlib import suppress
from datetime import timedelta
from uuid import UUID

from qq_time_agent.adapters.inbound.qq.message_syntax import (
    as_forwarded,
    as_note,
    forwarded,
    noted,
    subject,
)
from qq_time_agent.contracts.clock import Clock
from qq_time_agent.contracts.jobs import JobQueue, JobRequest
from qq_time_agent.contracts.message_presentation import format_direct_reply
from qq_time_agent.contracts.source import (
    SourceAssetDescriptor,
    SourceAssetDiscoveryPort,
    SourceEnvelope,
    SourceType,
)
from qq_time_agent.modules.agent.application import ConversationTurnCoordinator
from qq_time_agent.modules.agent.application.turn_input import (
    LoadedTurnSegment,
    build_turn_input,
)
from qq_time_agent.modules.agent.contracts import (
    AgentContextAssemblyPort,
    AgentFinal,
    AgentRun,
    AgentRunCommandPort,
    AgentRunExecution,
    AgentRunExecutionStatus,
    AgentRunStatus,
    AgentTurnSegmentRef,
    AgentTurnTicket,
    ConversationSnapshot,
)
from qq_time_agent.modules.inbox.contracts import (
    InboxContentPort,
    InboxProcessingPort,
    IngestResult,
    QqInboxPort,
)
from qq_time_agent.modules.normalization.contracts import NormalizationPort

LOGGER = logging.getLogger(__name__)


class QqCommandRouter:
    def __init__(
        self,
        inbox: QqInboxPort,
        processing: InboxProcessingPort,
        normalization: NormalizationPort,
        jobs: JobQueue,
        clock: Clock,
        asset_discovery: SourceAssetDiscoveryPort | None,
        agent_context: AgentContextAssemblyPort,
        agent_runs: AgentRunCommandPort,
        display_name: str = "小智",
        *,
        turn_coordinator: ConversationTurnCoordinator | None = None,
        inbox_content: InboxContentPort | None = None,
    ) -> None:
        self._inbox = inbox
        self._processing = processing
        self._normalization = normalization
        self._jobs = jobs
        self._clock = clock
        self._agent_context = agent_context
        self._agent_runs = agent_runs
        self._asset_discovery = asset_discovery
        self._display_name = display_name
        self._turns = turn_coordinator
        self._inbox_content = inbox_content

    async def receive(
        self,
        envelope: SourceEnvelope,
        content: str,
        assets: tuple[SourceAssetDescriptor, ...] = (),
    ) -> str | None:
        LOGGER.info(
            "QQ 消息进入路由: 开始判断处理路径",
            extra={
                "role": "qq",
                "source_type": envelope.source_type.value,
                "content_chars": len(content),
                "path": "asset" if assets else "text",
            },
        )
        if assets:
            return await self._ingest_text(envelope, content, assets)
        is_note, note_text = noted(content)
        if is_note:
            note_envelope = as_note(envelope, note_text)
            return await self._ingest_text(note_envelope, note_text)
        if self._turns is not None:
            return await self._receive_coalesced(envelope, content)
        is_forwarded, text = forwarded(content)
        if is_forwarded:
            forwarded_envelope = as_forwarded(envelope, text)
            return await self._ingest_text(forwarded_envelope, text)
        return await self._agent_reply(envelope, text)

    async def _receive_coalesced(self, envelope: SourceEnvelope, content: str) -> str | None:
        if self._inbox_content is None or self._turns is None:
            raise RuntimeError("QQ turn coordination dependencies are incomplete")
        is_forwarded, text = forwarded(content)
        staged_envelope = as_forwarded(envelope, text) if is_forwarded else envelope
        ingested = await self._inbox.ingest_qq(staged_envelope, text)
        await self._normalize_ingested_text(staged_envelope, text, ingested)
        ticket = await self._turns.stage(
            user_id="owner",
            conversation_key=envelope.thread_id or envelope.sender.provider_id,
            inbox_item_id=ingested.inbox_item_id,
            source_type=staged_envelope.source_type.value,
            trust_level=staged_envelope.trust_level.value,
            occurred_at=staged_envelope.occurred_at,
            provider_sequence=_provider_sequence(envelope),
            reference_hash=envelope.metadata.get("message_reference_hash"),
            content_chars=len(text),
        )
        await self._schedule_turn_recovery(ticket)
        claim = await self._turns.settle(ticket)
        if claim is None:
            return None
        try:
            reply = await self._execute_turn(
                claim.segments,
                envelope,
                ingested.inbox_item_id,
                claim.conversation_key_hash,
            )
            await self._turns.complete(claim)
            return reply
        except (LookupError, ValueError) as exc:
            with suppress(Exception):
                await self._turns.fail(claim, type(exc).__name__)
            raise
        except Exception:
            with suppress(Exception):
                await self._turns.release(claim)
            raise

    async def _execute_turn(
        self,
        refs: tuple[AgentTurnSegmentRef, ...],
        envelope: SourceEnvelope,
        current_inbox_item_id: UUID,
        conversation_key_hash: str,
    ) -> str:
        assert self._inbox_content is not None
        loaded: list[LoadedTurnSegment] = []
        for ref in refs:
            content = await self._inbox_content.get_content(ref.inbox_item_id)
            if content is None or content.deleted_at is not None:
                raise LookupError("QQ turn source content is unavailable")
            loaded.append(LoadedTurnSegment(ref, content.body_text))
        turn_input = build_turn_input(tuple(loaded))
        LOGGER.info(
            "QQ 连续消息批次已封口",
            extra={
                "role": "qq",
                "message_count": len(loaded),
                "evidence_count": 0
                if turn_input is None
                else len(turn_input.evidence_inbox_item_ids),
            },
        )
        if turn_input is None:
            return self._format_direct_reply("已接收转发文本, 将用于后续检索。")
        if turn_input.command_inbox_item_id != current_inbox_item_id:
            raise RuntimeError("QQ turn callback does not own the latest command")
        source_refs = tuple(f"inbox:{item_id}" for item_id in turn_input.related_inbox_item_ids)
        return await self._agent_reply_from_ingested(
            envelope,
            turn_input.live_message,
            current_inbox_item_id,
            turn_input.evidence_context,
            source_refs,
            f"qq-turn:{conversation_key_hash}",
        )

    async def _schedule_turn_recovery(self, ticket: AgentTurnTicket) -> None:
        try:
            await self._jobs.enqueue(
                JobRequest(
                    "qq-turn",
                    {"turn_id": str(ticket.turn_id), "generation": ticket.generation},
                    f"qq-turn:{ticket.turn_id}:g{ticket.generation}",
                    ticket.ready_at + timedelta(seconds=10),
                )
            )
        except Exception:
            LOGGER.exception(
                "QQ turn 恢复任务入队失败: 继续当前安全执行",
                extra={"role": "qq", "path": "turn"},
            )

    async def _agent_reply(self, envelope: SourceEnvelope, content: str) -> str:
        ingested = await self._inbox.ingest_qq(envelope, content)
        await self._normalize_ingested_text(envelope, content, ingested)
        return await self._agent_reply_from_ingested(
            envelope, content, ingested.inbox_item_id, "", (), None
        )

    async def _agent_reply_from_ingested(
        self,
        envelope: SourceEnvelope,
        content: str,
        inbox_item_id: UUID,
        turn_context: str,
        source_refs: tuple[str, ...],
        conversation_key: str | None,
    ) -> str:
        run = await self._agent_runs.ensure_run(
            inbox_item_id,
            "owner",
            envelope.source_type.value,
            conversation_key=(
                conversation_key or envelope.thread_id or envelope.sender.provider_id
            ),
            occurred_at=envelope.occurred_at,
            message=content,
            source_refs=source_refs,
        )
        if run.status is AgentRunStatus.COMPLETED:
            if run.final_content is None or run.final_delivery is None:
                raise ValueError("Completed AgentRun is missing its persisted final response")
            return self._format_direct_reply(run.final_content)
        # The immediate QQ path owns this attempt; the delayed job is crash recovery.
        recovery_available = True
        try:
            await self._jobs.enqueue(
                JobRequest(
                    "agent-run",
                    {"run_id": str(run.run_id), "inbox_item_id": str(inbox_item_id)},
                    f"agent-run:{run.run_id}",
                    self._clock.now() + timedelta(seconds=30),
                )
            )
        except Exception:
            recovery_available = False
            LOGGER.exception(
                "QQ Agent 恢复任务入队失败: 继续当前安全执行",
                extra={"role": "qq", "path": "agent", "run_id": str(run.run_id)},
            )
        try:
            assembled = await self._agent_context.assemble(
                "owner",
                content,
                before=envelope.occurred_at,
                exclude_id=inbox_item_id,
                conversation_id=run.conversation_id,
                event_case_id=run.event_case_id,
                run_id=run.run_id,
                snapshot=_run_snapshot(run),
            )
        except Exception as exc:
            with suppress(Exception):
                await self._agent_runs.fail_before_execution(run.run_id, type(exc).__name__)
            raise
        execution_context = assembled.context
        if turn_context:
            execution_context = f"{execution_context}\n\n{turn_context}".strip()
        raw_outcome = await self._agent_runs.execute(
            run.run_id, content, execution_context, assembled.messages, assembled.snapshot
        )
        outcome = _execution_outcome(raw_outcome)
        if outcome.status is AgentRunExecutionStatus.IN_PROGRESS:
            message = "正在处理中, 请稍后查看结果。"
            if not recovery_available:
                message = "正在处理中, 但自动恢复暂不可用, 请稍后重试。"
            return self._format_direct_reply(message)
        if outcome.final is None:
            raise RuntimeError("AgentRun completed without a final response")
        result = outcome.final
        LOGGER.info(
            "QQ Agent 处理完成: 返回用户答复",
            extra={
                "role": "qq",
                "path": "agent",
                "result_type": "agent_final",
                "result_chars": len(result.content),
                "context_chars": len(execution_context),
                "timeline_messages": len(assembled.messages),
            },
        )
        return self._format_direct_reply(result.content)

    async def _ingest_text(
        self,
        envelope: SourceEnvelope,
        text: str,
        assets: tuple[SourceAssetDescriptor, ...] = (),
    ) -> str:
        result = await self._inbox.ingest_qq(envelope, text, has_assets=bool(assets))
        await self._normalize_ingested_text(envelope, text, result, assets)
        if envelope.source_type is SourceType.OWNER_NOTE:
            return self._format_direct_reply("已保存主人笔记, 将用于后续检索。")
        if assets:
            return self._format_direct_reply("已接收图片, 正在离线识别并生成建议。")
        label = "转发文本" if envelope.source_type is SourceType.QQ_FORWARD else "输入"
        return self._format_direct_reply(f"已接收{label}, 将用于后续检索。")

    def _format_direct_reply(self, content: str) -> str:
        return format_direct_reply(self._display_name, content)

    async def _normalize_ingested_text(
        self,
        envelope: SourceEnvelope,
        text: str,
        result: IngestResult,
        assets: tuple[SourceAssetDescriptor, ...] = (),
    ) -> None:
        if not result.created:
            return
        if assets and self._asset_discovery is not None:
            await self._asset_discovery.discover(result.inbox_item_id, assets, self._clock.now())
        await self._normalization.normalize(
            result.inbox_item_id,
            subject(envelope.source_type),
            text,
            None,
            envelope.content_hash.removeprefix("sha256:"),
            result.source_ref,
        )
        await self._processing.mark_normalized(result.inbox_item_id)
        if envelope.source_type is SourceType.OWNER_NOTE:
            await self._processing.mark_completed(result.inbox_item_id)


def _run_snapshot(run: AgentRun) -> ConversationSnapshot | None:
    if (
        run.context_revision is None
        or run.context_max_sequence is None
        or run.context_hash is None
        or run.conversation_id is None
    ):
        return None
    return ConversationSnapshot(
        user_id=run.user_id,
        scope_id=run.conversation_id,
        revision=run.context_revision,
        max_sequence=run.context_max_sequence,
        context_hash=run.context_hash,
    )


def _execution_outcome(value: AgentRunExecution | AgentFinal) -> AgentRunExecution:
    if isinstance(value, AgentRunExecution):
        return value
    return AgentRunExecution(AgentRunExecutionStatus.EXECUTED, value)


def _provider_sequence(envelope: SourceEnvelope) -> int | None:
    value = envelope.metadata.get("provider_sequence")
    if value is None:
        return None
    try:
        parsed = int(value)
    except ValueError:
        return None
    return parsed if parsed >= 0 else None
