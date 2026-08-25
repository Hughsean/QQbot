"""Bounded runtime context assembly for Agent turns."""

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

    async def build(self, user_id: str, message: str) -> str:
        chunks = await self._retrieval.retrieve(message, RetrievalFilters(), 6)
        blocks = [
            (
                f"[knowledge T2] {item.source_ref} {item.occurred_at.isoformat()}\n"
                f"{item.content[:1600]}"
            )
            for item in chunks
        ]
        return "\n\n".join(blocks)[:12000]
