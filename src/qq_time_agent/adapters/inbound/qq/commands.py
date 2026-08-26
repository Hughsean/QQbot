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
from qq_time_agent.contracts.source import (
    SourceAssetDescriptor,
    SourceAssetDiscoveryPort,
    SourceEnvelope,
    SourceType,
)
from qq_time_agent.modules.agent.contracts import AgentContextPort, AgentRunCommandPort
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
    ) -> None:
        self._inbox = inbox
        self._processing = processing
        self._normalization = normalization
        self._jobs = jobs
        self._clock = clock
        self._agent_context = agent_context
        self._agent_runs = agent_runs
        self._asset_discovery = asset_discovery

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
        # The immediate QQ path owns this attempt; the delayed job is crash recovery.
        await self._jobs.enqueue(
            JobRequest(
                "agent-run",
                {"run_id": str(run.run_id), "inbox_item_id": str(ingested.inbox_item_id)},
                f"agent-run:{run.run_id}",
                self._clock.now() + timedelta(seconds=30),
            )
        )
        context = await self._agent_context.build(
            "owner",
            content,
            before=envelope.occurred_at,
            exclude_id=ingested.inbox_item_id,
            conversation_id=run.conversation_id,
            event_case_id=run.event_case_id,
        )
        result = await self._agent_runs.execute(run.run_id, content, context)
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
        return result.content

    async def _ingest_text(
        self,
        envelope: SourceEnvelope,
        text: str,
        assets: tuple[SourceAssetDescriptor, ...] = (),
    ) -> str:
        result = await self._inbox.ingest_qq(envelope, text)
        await self._normalize_ingested_text(envelope, text, result, assets)
        if envelope.source_type is SourceType.OWNER_NOTE:
            return "已保存主人笔记, 将用于后续检索。"
        if assets:
            return "已接收图片, 正在离线识别并生成建议。"
        label = "转发文本" if envelope.source_type is SourceType.QQ_FORWARD else "输入"
        return f"已接收{label}, 将用于后续检索。"

    async def _normalize_ingested_text(
        self,
        envelope: SourceEnvelope,
        text: str,
        result: IngestResult,
        assets: tuple[SourceAssetDescriptor, ...] = (),
    ) -> None:
        if assets and self._asset_discovery is not None:
            await self._asset_discovery.discover(result.inbox_item_id, assets, self._clock.now())
        if result.created:
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
