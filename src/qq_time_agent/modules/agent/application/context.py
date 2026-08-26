"""Bounded runtime context assembly for Agent turns."""

from datetime import datetime
from uuid import UUID

from qq_time_agent.modules.inbox.contracts import ConversationContextPort
from qq_time_agent.modules.retrieval.contracts import RetrievalFilters, RetrievalPort


class AgentContextAssembler:
    def __init__(
        self,
        retrieval: RetrievalPort,
        conversation: ConversationContextPort | None = None,
    ) -> None:
        self._retrieval = retrieval
        self._conversation = conversation

    async def build(
        self,
        user_id: str,
        message: str,
        before: datetime | None = None,
        exclude_id: UUID | None = None,
    ) -> str:
        chunks = await self._retrieval.retrieve(message, RetrievalFilters(), 6)
        blocks = [
            (
                f"[knowledge T2] {item.source_ref} {item.occurred_at.isoformat()}\n"
                f"{item.content[:1600]}"
            )
            for item in chunks
        ]
        if self._conversation is not None and before is not None and exclude_id is not None:
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
