"""Knowledge-owned idempotent deletion adapter."""

from uuid import UUID

from qq_time_agent.modules.data_lifecycle.contracts import PurgeResult
from qq_time_agent.modules.knowledge.infrastructure.repository import SqlKnowledgeRepository


class KnowledgePurgeAdapter:
    module_name = "knowledge"

    def __init__(self, repository: SqlKnowledgeRepository) -> None:
        self._repository = repository

    async def purge_subject(self, subject_ref: str, tombstone_id: UUID) -> PurgeResult:
        del tombstone_id
        count = await self._repository.delete_source(subject_ref)
        return PurgeResult(self.module_name, count, count == 0)
