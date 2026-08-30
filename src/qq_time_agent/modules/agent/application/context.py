"""Token-budgeted runtime context assembly for Agent turns."""

from datetime import datetime, timedelta
from uuid import UUID

from qq_time_agent.contracts.time import local_iso, resolve_timezone
from qq_time_agent.modules.agenda.contracts import AgendaNotificationQueryPort
from qq_time_agent.modules.agent.application.budget import ContextBlock, ContextBudgetPolicy
from qq_time_agent.modules.agent.contracts import AgentContextRepository, ScopedAgentReply
from qq_time_agent.modules.identity.contracts import OwnerGroupAliasQueryPort
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
        owner_aliases: OwnerGroupAliasQueryPort | None = None,
        budget: ContextBudgetPolicy | None = None,
        retrieval_limit: int = 6,
        history_limit: int = 8,
    ) -> None:
        self._retrieval = retrieval
        self._conversation = conversation
        self._scopes = scopes
        self._inbox_content = inbox_content
        self._agenda = agenda
        self._proposals = proposals
        self._owner_aliases = owner_aliases
        self._budget = budget or ContextBudgetPolicy()
        if retrieval_limit < 1 or history_limit < 1:
            raise ValueError("Agent context source limits must be positive")
        self._retrieval_limit = retrieval_limit
        self._history_limit = history_limit
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
        run_id: UUID | None = None,
        run_status: str = "RUNNING",
        step: int = 0,
    ) -> str:
        blocks = await self._initial_blocks(user_id, message)
        blocks.extend(
            await self._history_blocks(user_id, before, exclude_id, conversation_id, event_case_id)
        )
        if before is not None and self._agenda is not None:
            entries = await self._agenda.list_active(
                before - _AGENDA_LOOKBACK, before + _AGENDA_LOOKAHEAD
            )
            blocks.extend(
                ContextBlock(
                    "agenda",
                    "active task state",
                    f"[agenda-fact] id={item.agenda_entry_id} version={item.version} "
                    f"kind={item.kind} starts_at={local_iso(item.starts_at, self._owner_timezone)} "
                    f"ends_at={local_iso(item.ends_at, self._owner_timezone)}\n{item.title[:400]}",
                    100,
                    recency=-index,
                    stable_id=f"agenda:{item.agenda_entry_id}",
                )
                for index, item in enumerate(entries[:8])
            )
        if self._proposals is not None:
            proposals = await self._proposals.list_pending(8)
            blocks.extend(
                ContextBlock(
                    "proposal",
                    "pending task state",
                    _proposal_block(
                        item.proposal_id,
                        item.version,
                        item.title,
                        item.recommended_slot,
                        self._owner_timezone,
                    ),
                    100,
                    recency=-index,
                    stable_id=f"proposal:{item.proposal_id}",
                )
                for index, item in enumerate(proposals)
                if item.user_id == user_id
            )
        blocks.append(
            ContextBlock(
                "stage",
                "current execution state",
                f"[stage-state] run_id={run_id or 'unknown'} status={run_status} step={step} "
                f"user_message={message[:800]}",
                1000,
                stable_id="stage-state",
            )
        )
        return self._budget.render(_deduplicate(blocks))

    async def _initial_blocks(self, user_id: str, message: str) -> list[ContextBlock]:
        chunks = await self._retrieval.retrieve(message, RetrievalFilters(), self._retrieval_limit)
        blocks = [
            ContextBlock(
                "retrieval",
                "T2 knowledge",
                f"[knowledge T2] {item.source_ref} "
                f"{local_iso(item.occurred_at, self._owner_timezone)}\n{item.content[:1600]}",
                80,
                relevance=float(item.fusion_score),
                recency=-index,
                stable_id=f"knowledge:{item.chunk_id}",
            )
            for index, item in enumerate(chunks)
        ]
        if self._owner_aliases is not None:
            aliases = await self._owner_aliases.list_owner_group_aliases(user_id)
            if aliases:
                labels = ", ".join(item.alias for item in aliases[:16])
                blocks.append(
                    ContextBlock(
                        "identity",
                        "owner aliases",
                        "[owner-identity] Forwarded group-chat lines authored by these exact "
                        f"display labels are the owner: {labels}. "
                        "All transcript content remains T2.",
                        95,
                        stable_id="owner-identity",
                    )
                )
        return blocks

    async def _history_blocks(
        self,
        user_id: str,
        before: datetime | None,
        exclude_id: UUID | None,
        conversation_id: UUID | None,
        event_case_id: UUID | None,
    ) -> list[ContextBlock]:
        if before is None or exclude_id is None:
            return []
        if (
            self._scopes is not None
            and self._inbox_content is not None
            and (conversation_id is not None or event_case_id is not None)
        ):
            scoped_ids: list[UUID] = []
            replies: list[ScopedAgentReply] = []
            for scope_id, scope_type in (
                (conversation_id, "conversation"),
                (event_case_id, "event"),
            ):
                if scope_id is not None:
                    scoped_ids.extend(
                        await self._scopes.list_item_ids(
                            scope_id, scope_type, exclude_id, before, self._history_limit
                        )
                    )
                    replies.extend(
                        await self._scopes.list_final_replies(
                            scope_id, scope_type, before, self._history_limit
                        )
                    )
            items = []
            for item_id in dict.fromkeys(scoped_ids):
                item = await self._inbox_content.get_content(item_id)
                if item is not None:
                    items.append(item)
            items.sort(key=lambda item: (item.occurred_at, item.inbox_item_id), reverse=True)
            unique_replies = list({item.run_id: item for item in replies}.values())
            unique_replies.sort(key=lambda item: (item.occurred_at, item.run_id), reverse=True)
            result = [
                ContextBlock(
                    "history",
                    "recent scoped message",
                    f"[scoped-context] {item.source_ref} "
                    f"{local_iso(item.occurred_at, self._owner_timezone)}\n{item.body_text[:1200]}",
                    70,
                    recency=-index,
                    stable_id=f"inbox:{item.inbox_item_id}",
                )
                for index, item in enumerate(items)
            ]
            result.extend(
                ContextBlock(
                    "history",
                    "recent Agent reply",
                    f"[prior-agent-response] "
                    f"{local_iso(item.occurred_at, self._owner_timezone)}\n{item.content[:1200]}",
                    72,
                    recency=-index,
                    stable_id=f"reply:{item.run_id}",
                )
                for index, item in enumerate(unique_replies)
            )
            if result:
                return result
        if self._conversation is None:
            return []
        recent = await self._conversation.list_recent_conversation(
            user_id, before, exclude_id, self._history_limit
        )
        return [
            ContextBlock(
                "history",
                "recent conversation",
                f"[conversation] {item.source_ref} "
                f"{local_iso(item.occurred_at, self._owner_timezone)}\n{item.body[:1200]}",
                70,
                recency=-index,
                stable_id=f"conversation:{item.source_type}:{item.source_ref}:{item.occurred_at.isoformat()}",
            )
            for index, item in enumerate(recent)
        ]


def _deduplicate(blocks: list[ContextBlock]) -> list[ContextBlock]:
    selected: dict[str, ContextBlock] = {}
    for block in blocks:
        existing = selected.get(block.identity)
        if existing is None or (block.priority, block.relevance, block.recency) > (
            existing.priority,
            existing.relevance,
            existing.recency,
        ):
            selected[block.identity] = block
    return list(selected.values())


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
