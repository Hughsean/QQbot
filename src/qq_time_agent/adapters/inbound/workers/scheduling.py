"""Thin scheduling handler; Proposal creation remains side-effect free."""

from typing import Protocol
from uuid import UUID

from qq_time_agent.adapters.inbound.workers.runner import RetryableJobError
from qq_time_agent.contracts.jobs import JobLease
from qq_time_agent.modules.inbox.contracts import InboxProcessingPort, InboxSourcePort
from qq_time_agent.modules.scheduling.contracts import SchedulingPort
from qq_time_agent.modules.understanding.contracts import CandidateQueryPort


class SchedulingJobHandler:
    def __init__(
        self,
        scheduling: SchedulingPort,
        candidates: CandidateQueryPort,
        inbox: InboxProcessingPort,
        sources: InboxSourcePort,
    ) -> None:
        self._scheduling = scheduling
        self._candidates = candidates
        self._inbox = inbox
        self._sources = sources

    async def __call__(self, job: JobLease) -> None:
        raw_id = job.payload.get("candidate_id")
        if not isinstance(raw_id, str):
            raise ValueError("scheduling job candidate_id is required")
        candidate_id = UUID(raw_id)
        candidate = await self._candidates.get_candidate(candidate_id)
        if candidate is None:
            raise LookupError("candidate does not exist")
        source = await self._sources.get_source(candidate.inbox_item_id)
        if source is None or source.deleted:
            raise LookupError("active Inbox source does not exist")
        if source.status == "NORMALIZED":
            raise RetryableJobError("PrerequisiteNotReady")
        if source.status not in {"UNDERSTOOD", "PROPOSED"}:
            raise ValueError("Inbox item is not eligible for scheduling")
        await self._scheduling.propose("owner", candidate_id)
        await self._inbox.mark_proposed(candidate.inbox_item_id)


class SchedulingCandidateSource(Protocol):
    async def list_candidate_ids(self, limit: int) -> tuple[UUID, ...]: ...
