"""Owner-only QQ command routing; forwarded content never reaches this parser."""

import logging
from datetime import datetime, timedelta
from uuid import UUID

from qq_time_agent.adapters.inbound.qq.message_syntax import (
    ParsedCommand,
)
from qq_time_agent.adapters.inbound.qq.message_syntax import (
    as_forwarded as _as_forwarded,
)
from qq_time_agent.adapters.inbound.qq.message_syntax import (
    as_note as _as_note,
)
from qq_time_agent.adapters.inbound.qq.message_syntax import (
    count as _count,
)
from qq_time_agent.adapters.inbound.qq.message_syntax import (
    format_answer as _format_answer,
)
from qq_time_agent.adapters.inbound.qq.message_syntax import (
    forwarded as _forwarded,
)
from qq_time_agent.adapters.inbound.qq.message_syntax import (
    looks_like_time_management as _looks_like_time_management,
)
from qq_time_agent.adapters.inbound.qq.message_syntax import (
    natural_reminder as _natural_reminder,
)
from qq_time_agent.adapters.inbound.qq.message_syntax import (
    noted as _noted,
)
from qq_time_agent.adapters.inbound.qq.message_syntax import (
    parse_command as _parse_command,
)
from qq_time_agent.adapters.inbound.qq.message_syntax import (
    parse_duration as _parse_duration,
)
from qq_time_agent.adapters.inbound.qq.message_syntax import (
    questioned as _questioned,
)
from qq_time_agent.adapters.inbound.qq.message_syntax import (
    subject as _subject,
)
from qq_time_agent.contracts.clock import Clock
from qq_time_agent.contracts.jobs import JobQueue, JobRequest
from qq_time_agent.contracts.source import (
    SourceAssetDescriptor,
    SourceAssetDiscoveryPort,
    SourceEnvelope,
    SourceType,
)
from qq_time_agent.modules.actions.contracts import ActionCommandPort
from qq_time_agent.modules.agenda.contracts import AgendaCommandPort, AgendaQueryPort
from qq_time_agent.modules.agent.application.run_service import AgentRunService
from qq_time_agent.modules.agent.contracts import AgentContextPort, AgentRunPort
from qq_time_agent.modules.ai_gateway.contracts import GeneralAnswerPort, RagAnswerPort
from qq_time_agent.modules.data_lifecycle.contracts import DeletionRequestPort
from qq_time_agent.modules.inbox.contracts import InboxProcessingPort, IngestResult, QqInboxPort
from qq_time_agent.modules.normalization.contracts import NormalizationPort
from qq_time_agent.modules.reminders.contracts import ReminderCommandPort
from qq_time_agent.modules.scheduling.contracts import SchedulingPort
from qq_time_agent.modules.understanding.contracts import CandidateQueryPort

LOGGER = logging.getLogger(__name__)


class QqCommandRouter:
    def __init__(
        self,
        inbox: QqInboxPort,
        processing: InboxProcessingPort,
        normalization: NormalizationPort,
        scheduling: SchedulingPort,
        candidates: CandidateQueryPort,
        actions: ActionCommandPort,
        agenda_query: AgendaQueryPort,
        agenda_commands: AgendaCommandPort,
        reminders: ReminderCommandPort,
        jobs: JobQueue,
        clock: Clock,
        reminder_lead_minutes: int,
        rag: RagAnswerPort | None = None,
        deletion: DeletionRequestPort | None = None,
        asset_discovery: SourceAssetDiscoveryPort | None = None,
        general_answer: GeneralAnswerPort | None = None,
        agent: AgentRunPort | None = None,
        agent_context: AgentContextPort | None = None,
        agent_runs: AgentRunService | None = None,
    ) -> None:
        self._inbox = inbox
        self._processing = processing
        self._normalization = normalization
        self._scheduling = scheduling
        self._candidates = candidates
        self._actions = actions
        self._agenda_query = agenda_query
        self._agenda_commands = agenda_commands
        self._reminders = reminders
        self._jobs = jobs
        self._clock = clock
        self._reminder_lead_minutes = reminder_lead_minutes
        self._rag = rag
        self._general_answer = general_answer
        self._agent = agent
        self._agent_context = agent_context
        self._agent_runs = agent_runs
        self._deletion = deletion
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
        forwarded, text = _forwarded(content)
        if forwarded:
            forwarded_envelope = _as_forwarded(envelope, text)
            return await self._ingest_text(forwarded_envelope, text)
        noted, text = _noted(text)
        if noted:
            note_envelope = _as_note(envelope, text)
            return await self._ingest_text(note_envelope, text)
        if self._agent is not None and envelope.source_type is SourceType.QQ_DIRECT:
            return await self._agent_reply(envelope, content)
        return await self._dispatch_text(envelope, text)

    async def _agent_reply(self, envelope: SourceEnvelope, content: str) -> str:
        agent = self._agent
        if agent is None:
            raise RuntimeError("Agent is not configured")
        ingested = await self._inbox.ingest_qq(envelope, content)
        await self._normalize_ingested_text(envelope, content, ingested)
        run = None
        if self._agent_runs is not None:
            run = await self._agent_runs.ensure_run(
                ingested.inbox_item_id,
                "owner",
                envelope.source_type.value,
                conversation_key=envelope.thread_id or envelope.sender.provider_id,
                occurred_at=envelope.occurred_at,
            )
            await self._jobs.enqueue(
                JobRequest(
                    "agent-run",
                    {"run_id": str(run.run_id), "inbox_item_id": str(ingested.inbox_item_id)},
                    f"agent-run:{run.run_id}",
                    self._clock.now(),
                )
            )
        context = ""
        if self._agent_context is not None:
            context = await self._agent_context.build(
                "owner",
                content,
                before=envelope.occurred_at,
                exclude_id=ingested.inbox_item_id,
                conversation_id=None if run is None else run.conversation_id,
                event_case_id=None if run is None else run.event_case_id,
            )
        result = (
            await self._agent_runs.execute(run.run_id, content, context)
            if run is not None and self._agent_runs is not None
            else await agent.run("owner", content, context)
        )
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

    async def _dispatch_text(self, envelope: SourceEnvelope, text: str) -> str:
        questioned, text = _questioned(text)
        if questioned:
            if self._rag is None:
                return "资料查询暂不可用。"
            return _format_answer(await self._rag.answer(text))
        natural_reminder = _natural_reminder(text)
        if natural_reminder is not None:
            return await self._reschedule_by_title(*natural_reminder)
        command = _parse_command(text)
        if command is None:
            acknowledgement = await self._ingest_text(envelope, text)
            if self._general_answer is not None and not _looks_like_time_management(text):
                return _format_answer(await self._general_answer.answer_general(text))
            return acknowledgement
        return await self._handle(command)

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
                _subject(envelope.source_type),
                text,
                None,
                envelope.content_hash.removeprefix("sha256:"),
                result.source_ref,
            )
            await self._processing.mark_normalized(result.inbox_item_id)
            if envelope.source_type is SourceType.OWNER_NOTE:
                await self._processing.mark_completed(result.inbox_item_id)

    async def _handle(self, command: ParsedCommand) -> str:
        if command.name == "确认":
            return await self._confirm(command.arguments)
        if command.name == "拒绝":
            return await self._reject(command.arguments)
        if command.name == "修改":
            return await self._revise(command.arguments)
        if command.name == "撤销":
            return await self._undo(command.arguments)
        if command.name == "撤销确认":
            return await self._confirm_undo(command.arguments)
        if command.name == "完成":
            return await self._complete(command.arguments)
        if command.name == "推迟":
            return await self._snooze(command.arguments)
        if command.name == "提醒":
            return await self._remind(command.arguments)
        if command.name == "删除资料":
            return await self._delete_source(command.arguments)
        return "无法识别命令。"

    async def _confirm(self, args: tuple[str, ...]) -> str:
        _count(args, 1)
        pending = await self._scheduling.find_by_confirmation_token(args[0])
        if pending is None:
            return "确认码无效、已过期或已被处理。"
        confirmed = pending
        if pending.status == "PENDING_CONFIRMATION":
            confirmed = await self._scheduling.confirm(
                "owner", pending.proposal_id, pending.version, args[0]
            )
        result = await self._actions.execute_confirmed(confirmed, self._reminder_lead_minutes)
        candidate = await self._candidates.get_candidate(confirmed.candidate_id)
        if candidate is None:
            raise LookupError("Proposal candidate no longer exists")
        await self._processing.mark_completed(candidate.inbox_item_id)
        await self._scheduling.mark_executed(confirmed.proposal_id, confirmed.version)
        return f"日程已创建: {result.agenda_entry_id}"

    async def _reject(self, args: tuple[str, ...]) -> str:
        _count(args, 1)
        pending = await self._scheduling.find_by_confirmation_token(args[0])
        if pending is None:
            return "确认码无效、已过期或已被处理。"
        await self._scheduling.reject("owner", pending.proposal_id, pending.version)
        candidate = await self._candidates.get_candidate(pending.candidate_id)
        if candidate is None:
            raise LookupError("Proposal candidate no longer exists")
        await self._processing.mark_completed(candidate.inbox_item_id)
        return "建议已拒绝, 未写入日程。"

    async def _revise(self, args: tuple[str, ...]) -> str:
        _count(args, 2)
        pending = await self._scheduling.find_by_confirmation_token(args[0])
        if pending is None:
            return "确认码无效、已过期或已被处理。"
        index = int(args[1])
        slots = tuple(
            slot
            for slot in (pending.recommended_slot, *pending.alternative_slots)
            if slot is not None
        )
        if index < 1 or index > len(slots):
            raise ValueError("修改序号超出可选时段")
        revised = await self._scheduling.revise(
            "owner", pending.proposal_id, pending.version, slots[index - 1]
        )
        return f"建议已更新, 新确认码: {revised.proposal_id.hex[:8]}-{revised.version}"

    async def _undo(self, args: tuple[str, ...]) -> str:
        _count(args, 1)
        entry_id = UUID(args[0])
        entry = await self._agenda_query.get_entry(entry_id)
        if entry is None or entry.status != "ACTIVE":
            raise LookupError("活动日程不存在")
        request = await self._actions.request_undo("owner", entry_id, entry.version)
        return f"请回复: 撤销确认 {request.action_id} {request.confirmation_token}"

    async def _confirm_undo(self, args: tuple[str, ...]) -> str:
        _count(args, 2)
        result = await self._actions.confirm_undo("owner", UUID(args[0]), args[1])
        return f"日程已撤销: {result.agenda_entry_id}"

    async def _complete(self, args: tuple[str, ...]) -> str:
        _count(args, 1)
        entry_id = UUID(args[0])
        entry = await self._agenda_query.get_entry(entry_id)
        if entry is None:
            raise LookupError("日程不存在")
        await self._agenda_commands.complete_entry(
            entry_id, entry.version, f"agenda:{entry_id}:v{entry.version}:complete"
        )
        await self._reminders.cancel_for_entry(entry_id, entry.version)
        return f"已完成: {entry_id}"

    async def _snooze(self, args: tuple[str, ...]) -> str:
        _count(args, 2)
        minutes = int(args[1])
        if minutes < 1 or minutes > 1440:
            raise ValueError("推迟分钟数必须在 1 到 1440 之间")
        reminder = await self._reminders.snooze(
            UUID(args[0]), timedelta(minutes=minutes), self._clock.now()
        )
        return f"已推迟到 {reminder.due_at.isoformat(timespec='minutes')}"

    async def _remind(self, args: tuple[str, ...]) -> str:
        if len(args) < 3 or args[1] not in {"提前", "改为"}:
            raise ValueError("提醒格式: 提醒 <日程编号> 提前 <天/小时/分钟> 或 改为 <ISO时间>")
        entry_id = UUID(args[0])
        entry = await self._agenda_query.get_entry(entry_id)
        if entry is None or entry.status != "ACTIVE":
            raise LookupError("活动日程不存在")
        reminders = await self._reminders.list_for_entry(entry_id)
        active = [value for value in reminders if value.status not in {"CANCELLED", "DEAD_LETTER"}]
        if not active:
            raise LookupError("该日程没有可修改的提醒")
        current = min(active, key=lambda value: value.due_at)
        now = self._clock.now()
        if args[1] == "提前":
            due_at = current.due_at - _parse_duration(args[2])
        else:
            if len(args) != 3:
                raise ValueError("改为只接受一个 ISO-8601 时间")
            due_at = datetime.fromisoformat(args[2])
        if due_at.tzinfo is None or due_at.utcoffset() is None:
            raise ValueError("提醒时间必须包含时区")
        updated = await self._reminders.reschedule(current.reminder_id, due_at, now)
        return f"提醒已更新到 {updated.due_at.isoformat(timespec='minutes')}"

    async def _reschedule_by_title(self, title: str, duration: str) -> str:
        entries = await self._agenda_query.find_active_by_title(title)
        if not entries:
            return f"找不到活动日程《{title}》, 请改用: 提醒 <日程编号> 提前 {duration}。"
        if len(entries) > 1:
            ids = "、".join(str(entry.agenda_entry_id) for entry in entries[:3])
            return f"找到多个同名日程, 请指定编号: {ids}"
        return await self._remind((str(entries[0].agenda_entry_id), "提前", duration))

    async def _delete_source(self, args: tuple[str, ...]) -> str:
        _count(args, 2)
        if args[1] != "确认删除":
            raise ValueError("删除资料必须包含确认删除")
        if self._deletion is None:
            return "资料删除暂不可用。"
        result = await self._deletion.record_deletion(args[0])
        return f"资料已删除: {result.subject_ref}"
