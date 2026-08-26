"""Bounded runtime context assembly for Agent turns."""

from datetime import datetime
from uuid import UUID

from qq_time_agent.modules.agent.contracts import AgentContextRepository
from qq_time_agent.modules.inbox.contracts import ConversationContextPort, InboxContentPort
from qq_time_agent.modules.retrieval.contracts import RetrievalFilters, RetrievalPort


class AgentContextAssembler:
    def __init__(
        self,
        retrieval: RetrievalPort,
        conversation: ConversationContextPort | None = None,
        scopes: AgentContextRepository | None = None,
        inbox_content: InboxContentPort | None = None,
    ) -> None:
        self._retrieval = retrieval
        self._conversation = conversation
        self._scopes = scopes
        self._inbox_content = inbox_content

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
                f"[knowledge T2] {item.source_ref} {item.occurred_at.isoformat()}\n"
                f"{item.content[:1600]}"
            )
            for item in chunks
        ]
        scoped_ids: list[UUID] = []
        if self._scopes is not None and self._inbox_content is not None and exclude_id is not None:
            for scope_id, scope_type in (
                (conversation_id, "conversation"),
                (event_case_id, "event"),
            ):
                if scope_id is not None:
                    scoped_ids.extend(
                        await self._scopes.list_item_ids(scope_id, scope_type, exclude_id, 8)
                    )
            scoped_items = []
            for item_id in dict.fromkeys(scoped_ids):
                item = await self._inbox_content.get_content(item_id)
                if item is not None:
                    scoped_items.append(item)
            blocks = [
                (
                    f"[scoped-context] {item.source_ref} "
                    f"{item.occurred_at.isoformat()}\n{item.body_text[:1200]}"
                )
                for item in scoped_items
            ] + blocks
        elif self._conversation is not None and before is not None and exclude_id is not None:
            recent = await self._conversation.list_recent_conversation(
                user_id, before, exclude_id, 8
            )
            blocks = [
                (
                    f"[conversation] {item.source_ref} "
                    f"{item.occurred_at.isoformat()}\n{item.body[:1200]}"
                )
                for item in recent
            ] + blocks
        return "\n\n".join(blocks)[:12000]
