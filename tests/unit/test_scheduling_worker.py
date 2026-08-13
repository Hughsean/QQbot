from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from qq_time_agent.adapters.inbound.workers.runner import RetryableJobError
from qq_time_agent.adapters.inbound.workers.scheduling import SchedulingJobHandler
from qq_time_agent.adapters.inbound.workers.scheduling_schedule import SchedulingScheduler
from qq_time_agent.contracts.jobs import JobLease, JobRequest, JobStatusView
from qq_time_agent.modules.inbox.contracts import InboxSourceView
from qq_time_agent.modules.scheduling.contracts import ProposalSlot, SchedulingProposalView
from qq_time_agent.modules.understanding.contracts import TaskCandidateView


@dataclass
class Candidates:
    value: TaskCandidateView

    async def get_candidate(self, candidate_id: UUID) -> TaskCandidateView | None:
        assert candidate_id == self.value.candidate_id
        return self.value

    async def list_candidate_ids(self, limit: int) -> tuple[UUID, ...]:
        return (self.value.candidate_id,)[:limit]


@dataclass
class Scheduling:
    fail: bool = False

    async def propose(self, user_id: str, candidate_id: UUID) -> SchedulingProposalView:
        if self.fail:
            raise RuntimeError("synthetic scheduling failure")
        return SchedulingProposalView(
            uuid4(),
            1,
            user_id,
            candidate_id,
            "TASK",
            "写报告",
            None,
            (),
            (),
            "none",
            (),
            (),
            datetime(2026, 8, 14, tzinfo=UTC),
            "PENDING_CONFIRMATION",
        )

    async def get_proposal(self, proposal_id: UUID) -> SchedulingProposalView | None:
        return None

    async def confirm(
        self, user_id: str, proposal_id: UUID, version: int, confirmation_token: str
    ) -> SchedulingProposalView:
        raise NotImplementedError

    async def revise(
        self, user_id: str, proposal_id: UUID, version: int, selected_slot: ProposalSlot
    ) -> SchedulingProposalView:
        raise NotImplementedError

    async def reject(self, user_id: str, proposal_id: UUID, version: int) -> SchedulingProposalView:
        raise NotImplementedError

    async def mark_executed(self, proposal_id: UUID, version: int) -> SchedulingProposalView:
        raise NotImplementedError

    async def find_by_confirmation_token(self, token: str) -> SchedulingProposalView | None:
        return None

    async def list_pending(self, limit: int) -> tuple[SchedulingProposalView, ...]:
        return ()


@dataclass
class Inbox:
    proposed: list[UUID] = field(default_factory=list)
    status: str = "UNDERSTOOD"

    async def mark_normalized(self, inbox_item_id: UUID) -> None:
        return None

    async def mark_understood(self, inbox_item_id: UUID) -> None:
        return None

    async def mark_needs_review(self, inbox_item_id: UUID) -> None:
        return None

    async def mark_ignored(self, inbox_item_id: UUID) -> None:
        return None

    async def mark_proposed(self, inbox_item_id: UUID) -> None:
        self.proposed.append(inbox_item_id)

    async def mark_completed(self, inbox_item_id: UUID) -> None:
        return None

    async def get_source(self, inbox_item_id: UUID) -> InboxSourceView | None:
        return InboxSourceView(
            inbox_item_id,
            "MICROSOFT_MAIL",
            "mail-1",
            None,
            "s***@example.test",
            "Subject",
            datetime(2026, 8, 13, tzinfo=UTC),
            self.status,
            False,
        )


@dataclass
class Clock:
    def now(self) -> datetime:
        return datetime(2026, 8, 13, tzinfo=UTC)


@dataclass
class Queue:
    requests: list[JobRequest] = field(default_factory=list)

    async def enqueue(self, request: JobRequest) -> UUID:
        self.requests.append(request)
        return uuid4()

    async def lease_due(
        self, now: datetime, worker_id: str, limit: int, lease_duration: timedelta
    ) -> list[JobLease]:
        return []

    async def complete(self, lease: JobLease, now: datetime) -> None:
        return None

    async def fail(
        self, lease: JobLease, now: datetime, failure_class: str, retry_at: datetime | None
    ) -> None:
        return None

    async def status(self, job_id: UUID) -> JobStatusView | None:
        return None


def _candidate() -> TaskCandidateView:
    return TaskCandidateView(
        uuid4(), uuid4(), "写报告", None, 60, None, (), 0.9, (), ("写报告",), ("inbox:test",)
    )


@pytest.mark.asyncio
async def test_handler_marks_proposed_only_after_proposal_succeeds() -> None:
    candidate = _candidate()
    inbox = Inbox()
    handler = SchedulingJobHandler(Scheduling(), Candidates(candidate), inbox, inbox)
    job = JobLease(
        uuid4(), "scheduling-propose", {"candidate_id": str(candidate.candidate_id)}, "worker", 1, 3
    )
    await handler(job)
    assert inbox.proposed == [candidate.inbox_item_id]

    inbox = Inbox()
    with pytest.raises(RuntimeError, match="synthetic"):
        await SchedulingJobHandler(Scheduling(True), Candidates(candidate), inbox, inbox)(job)
    assert inbox.proposed == []

    inbox = Inbox(status="NORMALIZED")
    with pytest.raises(RetryableJobError, match="PrerequisiteNotReady"):
        await SchedulingJobHandler(Scheduling(), Candidates(candidate), inbox, inbox)(job)
    assert inbox.proposed == []


@pytest.mark.asyncio
async def test_scheduler_enqueues_candidate_id_only_with_stable_key() -> None:
    candidate = _candidate()
    queue = Queue()
    await SchedulingScheduler(Candidates(candidate), queue, Clock()).enqueue_due()
    request = queue.requests[0]
    assert request.payload == {"candidate_id": str(candidate.candidate_id)}
    assert request.idempotency_key == f"scheduling:{candidate.candidate_id}:v1"
    assert "title" not in request.payload and "body" not in request.payload
