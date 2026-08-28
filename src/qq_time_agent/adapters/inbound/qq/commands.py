"""Owner-only QQ ingress routing with persistent AgentRun execution."""

import logging
from datetime import timedelta

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
from qq_time_agent.modules.agent.contracts import (
    AgentContextPort,
    AgentFinal,
    AgentRunCommandPort,
    AgentRunExecution,
    AgentRunExecutionStatus,
    AgentRunStatus,
)
from qq_time_agent.modules.inbox.contracts import InboxProcessingPort, IngestResult, QqInboxPort
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
        agent_context: AgentContextPort,
        agent_runs: AgentRunCommandPort,
        display_name: str = "小智",
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

    async def receive(
        self,
        envelope: SourceEnvelope,
        content: str,
        assets: tuple[SourceAssetDescriptor, ...] = (),
    ) -> str:
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
        is_forwarded, text = forwarded(content)
        if is_forwarded:
            forwarded_envelope = as_forwarded(envelope, text)
            return await self._ingest_text(forwarded_envelope, text)
        is_note, text = noted(text)
        if is_note:
            note_envelope = as_note(envelope, text)
            return await self._ingest_text(note_envelope, text)
        return await self._agent_reply(envelope, text)

    async def _agent_reply(self, envelope: SourceEnvelope, content: str) -> str:
        ingested = await self._inbox.ingest_qq(envelope, content)
        await self._normalize_ingested_text(envelope, content, ingested)
        run = await self._agent_runs.ensure_run(
            ingested.inbox_item_id,
            "owner",
            envelope.source_type.value,
            conversation_key=envelope.thread_id or envelope.sender.provider_id,
            occurred_at=envelope.occurred_at,
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
                    {"run_id": str(run.run_id), "inbox_item_id": str(ingested.inbox_item_id)},
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
        context = await self._agent_context.build(
            "owner",
            content,
            before=envelope.occurred_at,
            exclude_id=ingested.inbox_item_id,
            conversation_id=run.conversation_id,
            event_case_id=run.event_case_id,
        )
        raw_outcome = await self._agent_runs.execute(run.run_id, content, context)
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
                "context_chars": len(context),
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


def _execution_outcome(value: AgentRunExecution | AgentFinal) -> AgentRunExecution:
    if isinstance(value, AgentRunExecution):
        return value
    return AgentRunExecution(AgentRunExecutionStatus.EXECUTED, value)
