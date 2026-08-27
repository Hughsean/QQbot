"""Bounded runtime context assembly for Agent turns."""

from datetime import datetime, timedelta
from uuid import UUID

from qq_time_agent.contracts.time import local_iso, resolve_timezone
from qq_time_agent.modules.agenda.contracts import AgendaNotificationQueryPort
from qq_time_agent.modules.agent.contracts import AgentContextRepository, ScopedAgentReply
from qq_time_agent.modules.inbox.contracts import ConversationContextPort, InboxContentPort
from qq_time_agent.modules.retrieval.contracts import RetrievalFilters, RetrievalPort
from qq_time_agent.modules.scheduling.contracts import PendingProposalQueryPort

_AGENDA_LOOKBACK = timedelta(days=1)
_AGENDA_LOOKAHEAD = timedelta(days=90)


class AgentContextAssembler:
    def __init__(
        self,
        retrieval: RetrievalPort,
        conversation: ConversationContextPort | None = None,
        scopes: AgentContextRepository | None = None,
        inbox_content: InboxContentPort | None = None,
        agenda: AgendaNotificationQueryPort | None = None,
        proposals: PendingProposalQueryPort | None = None,
        owner_timezone: str = "Asia/Shanghai",
    ) -> None:
        self._retrieval = retrieval
        self._conversation = conversation
        self._scopes = scopes
        self._inbox_content = inbox_content
        self._agenda = agenda
        self._proposals = proposals
        resolve_timezone(owner_timezone)
        self._owner_timezone = owner_timezone

    async def build(
        self,
        user_id: str,
        message: str,
        before: datetime | None = None,
        exclude_id: UUID | None = None,
        conversation_id: UUID | None = None,
        event_case_id: UUID | None = None,
    ) -> str:
        chunks = await self._retrieval.retrieve(message, RetrievalFilters(), 6)
        blocks = [
            (
                f"[knowledge T2] {item.source_ref} "
                f"{local_iso(item.occurred_at, self._owner_timezone)}\n"
                f"{item.content[:1600]}"
            )
            for item in chunks
        ]
        scoped_ids: list[UUID] = []
        replies: list[ScopedAgentReply] = []
        if (
            self._scopes is not None
            and self._inbox_content is not None
            and exclude_id is not None
            and before is not None
        ):
            for scope_id, scope_type in (
                (conversation_id, "conversation"),
                (event_case_id, "event"),
            ):
                if scope_id is not None:
                    scoped_ids.extend(
                        await self._scopes.list_item_ids(
                            scope_id, scope_type, exclude_id, before, 8
                        )
                    )
                    replies.extend(
                        await self._scopes.list_final_replies(scope_id, scope_type, before, 8)
                    )
            scoped_items = []
            for item_id in dict.fromkeys(scoped_ids):
                item = await self._inbox_content.get_content(item_id)
                if item is not None:
                    scoped_items.append(item)
            scoped_items.sort(key=lambda item: (item.occurred_at, item.inbox_item_id), reverse=True)
            replies = list({item.run_id: item for item in replies}.values())
            replies.sort(key=lambda item: (item.occurred_at, item.run_id), reverse=True)
            blocks = (
                [
                    (
                        f"[scoped-context] {item.source_ref} "
                        f"{local_iso(item.occurred_at, self._owner_timezone)}\n"
                        f"{item.body_text[:1200]}"
                    )
                    for item in scoped_items
                ]
                + [
                    f"[prior-agent-response] "
                    f"{local_iso(item.occurred_at, self._owner_timezone)}\n"
                    f"{item.content[:1200]}"
                    for item in replies
                ]
                + blocks
            )
        elif self._conversation is not None and before is not None and exclude_id is not None:
            recent = await self._conversation.list_recent_conversation(
                user_id, before, exclude_id, 8
            )
            blocks = [
                (
                    f"[conversation] {item.source_ref} "
                    f"{local_iso(item.occurred_at, self._owner_timezone)}\n{item.body[:1200]}"
                )
                for item in recent
            ] + blocks
        if before is not None and self._agenda is not None:
            entries = await self._agenda.list_active(
                before - _AGENDA_LOOKBACK, before + _AGENDA_LOOKAHEAD
            )
            blocks = [
                (
                    f"[agenda-fact] id={item.agenda_entry_id} version={item.version} "
                    f"kind={item.kind} starts_at={local_iso(item.starts_at, self._owner_timezone)} "
                    f"ends_at={local_iso(item.ends_at, self._owner_timezone)}\n{item.title[:400]}"
                )
                for item in entries[:8]
            ] + blocks
        if self._proposals is not None:
            proposals = await self._proposals.list_pending(8)
            blocks = [
                _proposal_block(
                    item.proposal_id,
                    item.version,
                    item.title,
                    item.recommended_slot,
                    self._owner_timezone,
                )
                for item in proposals
                if item.user_id == user_id
            ] + blocks
        return "\n\n".join(blocks)[:12000]


def _proposal_block(
    proposal_id: UUID, version: int, title: str, slot: object, owner_timezone: str
) -> str:
    starts_at = getattr(slot, "starts_at", None)
    ends_at = getattr(slot, "ends_at", None)
    if isinstance(starts_at, datetime) and isinstance(ends_at, datetime):
        timing = (
            f"starts_at={local_iso(starts_at, owner_timezone)} "
            f"ends_at={local_iso(ends_at, owner_timezone)}"
        )
    else:
        timing = "no recommended slot"
    return f"[pending-proposal] id={proposal_id} version={version} {timing}\n{title[:400]}"
