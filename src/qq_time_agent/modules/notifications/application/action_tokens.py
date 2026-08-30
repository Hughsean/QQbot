"""Short-lived, single-use Reminder interaction tokens."""

import hashlib
import secrets
from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from qq_time_agent.modules.notifications.contracts import (
    ReminderActionToken,
    ReminderActionTokenPort,
)
from qq_time_agent.modules.notifications.infrastructure.tables import ReminderActionTokenRow


class ReminderActionTokenService(ReminderActionTokenPort):
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def issue(
        self,
        *,
        owner_id: str,
        reminder_id: UUID,
        agenda_entry_id: UUID,
        agenda_entry_version: int,
        occurrence: int,
        action_type: str,
        action_value: str | None,
        expires_at: datetime,
    ) -> str:
        if not owner_id.strip() or agenda_entry_version < 1 or occurrence < 1:
            raise ValueError("Reminder action token fields are invalid")
        if not action_type.strip() or expires_at.tzinfo is None:
            raise ValueError("Reminder action token expiry and type are required")
        token = secrets.token_urlsafe(32)
        token_hash = _hash(token)
        async with self._sessions.begin() as session:
            session.add(
                ReminderActionTokenRow(
                    token_hash=token_hash,
                    owner_id=owner_id,
                    reminder_id=reminder_id,
                    agenda_entry_id=agenda_entry_id,
                    agenda_entry_version=agenda_entry_version,
                    occurrence=occurrence,
                    action_type=action_type,
                    action_value=action_value,
                    expires_at=expires_at,
                )
            )
        return token

    async def claim(
        self,
        token: str,
        owner_id: str,
        expected_action_type: str,
        now: datetime,
    ) -> ReminderActionToken | None:
        if (
            not token
            or not owner_id.strip()
            or not expected_action_type.strip()
            or now.tzinfo is None
        ):
            return None
        token_hash = _hash(token)
        try:
            async with self._sessions.begin() as session:
                result = await session.execute(
                    update(ReminderActionTokenRow)
                    .where(
                        and_(
                            ReminderActionTokenRow.token_hash == token_hash,
                            ReminderActionTokenRow.owner_id == owner_id,
                            ReminderActionTokenRow.action_type == expected_action_type,
                            ReminderActionTokenRow.used_at.is_(None),
                            ReminderActionTokenRow.claimed_at.is_(None),
                            ReminderActionTokenRow.expires_at > now,
                        )
                    )
                    .values(used_at=now, claimed_at=now)
                    .returning(ReminderActionTokenRow)
                )
                row = result.fetchone()
                if row is None:
                    return None
                return _to_token(row[0])
        except IntegrityError as exc:
            if "uq_notifications_reminder_action_tokens_claim" not in str(exc.orig):
                raise
            return None

    async def resolve(self, token_hash: str, now: datetime, outcome: str) -> None:
        if not token_hash or now.tzinfo is None or not outcome.strip():
            return
        async with self._sessions.begin() as session:
            await session.execute(
                update(ReminderActionTokenRow)
                .where(
                    and_(
                        ReminderActionTokenRow.token_hash == token_hash,
                        ReminderActionTokenRow.claimed_at.is_not(None),
                        ReminderActionTokenRow.resolved_at.is_(None),
                    )
                )
                .values(resolved_at=now, outcome=outcome)
            )


def _to_token(value: ReminderActionTokenRow) -> ReminderActionToken:
    return ReminderActionToken(
        value.token_hash,
        value.owner_id,
        value.reminder_id,
        value.agenda_entry_id,
        value.agenda_entry_version,
        value.occurrence,
        value.action_type,
        value.action_value,
        value.expires_at,
        value.used_at,
        value.claimed_at,
        value.resolved_at,
        value.outcome,
    )


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
