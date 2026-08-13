"""Confirmed action execution and two-step undo contracts."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from qq_time_agent.modules.scheduling.contracts import SchedulingProposalView


@dataclass(frozen=True, slots=True)
class ActionResultView:
    action_id: UUID
    action_type: str
    status: str
    agenda_entry_id: UUID | None
    agenda_entry_version: int | None
    reminder_id: UUID | None


@dataclass(frozen=True, slots=True)
class UndoRequestView:
    action_id: UUID
    agenda_entry_id: UUID
    agenda_entry_version: int
    confirmation_token: str
    status: str


class ActionCommandPort(Protocol):
    async def execute_confirmed(
        self, proposal: SchedulingProposalView, reminder_lead_minutes: int
    ) -> ActionResultView: ...

    async def request_undo(
        self, user_id: str, entry_id: UUID, entry_version: int
    ) -> UndoRequestView: ...

    async def confirm_undo(
        self, user_id: str, action_id: UUID, confirmation_token: str
    ) -> ActionResultView: ...
