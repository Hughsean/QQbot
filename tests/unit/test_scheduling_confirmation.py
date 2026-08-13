from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from qq_time_agent.modules.scheduling.contracts import ProposalSlot, confirmation_token
from qq_time_agent.modules.scheduling.domain.models import ProposalStatus, SchedulingProposal


def _proposal() -> SchedulingProposal:
    start = datetime(2026, 8, 20, 7, tzinfo=UTC)
    return SchedulingProposal.create(
        "owner",
        uuid4(),
        "TASK",
        "写报告",
        ProposalSlot(start, start + timedelta(hours=1), "Asia/Shanghai"),
        (ProposalSlot(start + timedelta(hours=1), start + timedelta(hours=2), "Asia/Shanghai"),),
        (),
        "满足硬约束",
        (),
        ("inbox:test",),
        start + timedelta(days=1),
        {},
    )


def test_revision_increments_version_and_invalidates_old_confirmation() -> None:
    proposal = _proposal()
    old_token = confirmation_token(proposal.proposal_id, proposal.version)
    alternative = proposal.alternative_slots[0]
    proposal.revise("owner", 1, alternative, datetime(2026, 8, 20, tzinfo=UTC))
    assert proposal.version == 2 and proposal.recommended_slot == alternative
    with pytest.raises(ValueError, match="stale"):
        proposal.confirm("owner", 1, old_token, datetime(2026, 8, 20, tzinfo=UTC))
    proposal.confirm(
        "owner",
        2,
        confirmation_token(proposal.proposal_id, 2),
        datetime(2026, 8, 20, tzinfo=UTC),
    )
    assert proposal.status is ProposalStatus.CONFIRMED and proposal.version == 3
    proposal.mark_executed(3)
    assert proposal.status.value == "EXECUTED"


def test_confirmation_rejects_wrong_owner_token_expiry_and_unknown_slot() -> None:
    proposal = _proposal()
    now = datetime(2026, 8, 20, tzinfo=UTC)
    with pytest.raises(PermissionError):
        proposal.reject("intruder", 1, now)
    with pytest.raises(ValueError, match="token"):
        proposal.confirm("owner", 1, "wrong", now)
    with pytest.raises(ValueError, match="not part"):
        proposal.revise(
            "owner",
            1,
            ProposalSlot(now, now + timedelta(minutes=30), "UTC"),
            now,
        )
    with pytest.raises(ValueError, match="expired"):
        proposal.reject("owner", 1, datetime(2026, 8, 22, tzinfo=UTC))
    assert proposal.status is ProposalStatus.EXPIRED
