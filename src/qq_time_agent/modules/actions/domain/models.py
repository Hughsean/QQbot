"""Pure idempotent ActionRequest aggregate."""

import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4


class ActionType(StrEnum):
    CREATE_AGENDA = "CREATE_AGENDA"
    UPDATE_AGENDA = "UPDATE_AGENDA"
    COMPLETE_AGENDA = "COMPLETE_AGENDA"
    CANCEL_AGENDA = "CANCEL_AGENDA"
    UPDATE_REMINDER = "UPDATE_REMINDER"


class ActionStatus(StrEnum):
    PENDING_CONFIRMATION = "PENDING_CONFIRMATION"
    CONFIRMED = "CONFIRMED"
    EXECUTING = "EXECUTING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


@dataclass(slots=True)
class ActionRequest:
    action_id: UUID
    user_id: str
    action_type: ActionType
    idempotency_key: str
    status: ActionStatus
    requested_at: datetime
    proposal_id: UUID | None = None
    proposal_version: int | None = None
    agenda_entry_id: UUID | None = None
    agenda_entry_version: int | None = None
    reminder_id: UUID | None = None
    failure_class: str | None = None
    operation_payload: dict[str, object] | None = None

    @classmethod
    def create_agenda(
        cls, user_id: str, proposal_id: UUID, proposal_version: int, now: datetime
    ) -> "ActionRequest":
        _required(user_id, now)
        return cls(
            uuid4(),
            user_id,
            ActionType.CREATE_AGENDA,
            f"proposal:{proposal_id}:v{proposal_version}:create",
            ActionStatus.CONFIRMED,
            now,
            proposal_id,
            proposal_version,
        )

    @classmethod
    def request_cancel(
        cls, user_id: str, entry_id: UUID, entry_version: int, now: datetime
    ) -> "ActionRequest":
        _required(user_id, now)
        return cls(
            uuid4(),
            user_id,
            ActionType.CANCEL_AGENDA,
            f"agenda:{entry_id}:v{entry_version}:cancel",
            ActionStatus.PENDING_CONFIRMATION,
            now,
            agenda_entry_id=entry_id,
            agenda_entry_version=entry_version,
        )

    @classmethod
    def calendar_operation(
        cls,
        user_id: str,
        action_type: ActionType,
        idempotency_key: str,
        payload: Mapping[str, object],
        now: datetime,
    ) -> "ActionRequest":
        _required(user_id, now)
        if action_type not in {
            ActionType.CREATE_AGENDA,
            ActionType.UPDATE_AGENDA,
            ActionType.COMPLETE_AGENDA,
            ActionType.CANCEL_AGENDA,
            ActionType.UPDATE_REMINDER,
        }:
            raise ValueError("unsupported calendar action")
        if not idempotency_key.strip():
            raise ValueError("Action idempotency key is required")
        return cls(
            uuid4(),
            user_id,
            action_type,
            idempotency_key,
            ActionStatus.CONFIRMED,
            now,
            agenda_entry_id=_payload_uuid(payload, "agenda_entry_id"),
            agenda_entry_version=_payload_int(payload, "expected_version"),
            operation_payload=dict(payload),
        )

    @property
    def confirmation_token(self) -> str:
        return f"undo-{self.action_id.hex[:8]}"

    def confirm_cancel(self, user_id: str, token: str) -> None:
        if self.user_id != user_id:
            raise PermissionError("Action belongs to another user")
        if not secrets.compare_digest(token.casefold(), self.confirmation_token.casefold()):
            raise ValueError("Undo confirmation token is invalid")
        if self.status is ActionStatus.PENDING_CONFIRMATION:
            self.status = ActionStatus.CONFIRMED

    def start(self) -> None:
        if self.status is ActionStatus.SUCCEEDED:
            return
        if self.status is ActionStatus.EXECUTING:
            return
        if self.status not in {ActionStatus.CONFIRMED, ActionStatus.FAILED}:
            raise ValueError("Action is not confirmed")
        self.status = ActionStatus.EXECUTING
        self.failure_class = None

    def succeed(self, entry_id: UUID, entry_version: int, reminder_id: UUID | None = None) -> None:
        if self.status is not ActionStatus.EXECUTING:
            raise ValueError("Action is not executing")
        self.agenda_entry_id = entry_id
        self.agenda_entry_version = entry_version
        self.reminder_id = reminder_id
        self.status = ActionStatus.SUCCEEDED

    def fail(self, failure_class: str) -> None:
        if self.status is not ActionStatus.EXECUTING or not failure_class.strip():
            raise ValueError("executing Action and failure class are required")
        self.status = ActionStatus.FAILED
        self.failure_class = failure_class


def _required(user_id: str, now: datetime) -> None:
    if not user_id.strip():
        raise ValueError("Action user is required")
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Action time must be timezone-aware")


def _payload_uuid(payload: Mapping[str, object], key: str) -> UUID | None:
    value = payload.get(key)
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        try:
            return UUID(value)
        except ValueError as exc:
            raise ValueError(f"{key} must be a UUID") from exc
    raise ValueError(f"{key} must be a UUID")


def _payload_int(payload: Mapping[str, object], key: str) -> int | None:
    value = payload.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{key} must be positive")
    return value
