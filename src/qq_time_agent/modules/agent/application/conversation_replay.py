"""Safe local replay of redacted conversation timeline exports."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Protocol

from qq_time_agent.modules.agent.application.conversation_replay_input import (
    ReplayInputError as ReplayInputError,
)
from qq_time_agent.modules.agent.application.conversation_replay_input import load_replay_events
from qq_time_agent.modules.agent.contracts import ConversationEventRepository

__all__ = ["ConversationTimelineReplay", "ReplayInputError", "ReplayResult"]


@dataclass(frozen=True, slots=True)
class ReplayResult:
    """Metadata-only replay result safe for logs and operator output."""

    input_count: int
    inserted_count: int
    skipped_count: int
    failed_count: int
    user_hashes: tuple[str, ...]
    scope_hashes: tuple[str, ...]
    sequence_ranges: tuple[tuple[str, int, int], ...]


class ReplayClock(Protocol):
    def now(self) -> datetime: ...


class ConversationTimelineReplay:
    """Validate and append only local, redacted timeline exports."""

    def __init__(
        self,
        repository: ConversationEventRepository,
        *,
        clock: ReplayClock,
        fail_fast: bool = True,
    ) -> None:
        self._repository = repository
        self._clock = clock
        self._fail_fast = fail_fast

    async def replay_path(self, path: Path) -> ReplayResult:
        events = load_replay_events(path)
        inserted = 0
        skipped = 0
        failed = 0
        ranges: dict[str, list[int]] = {}
        users: set[str] = set()
        scopes: set[str] = set()
        for event in events:
            users.add(event.user_id)
            scopes.add(f"{event.scope_type.value}:{event.scope_id}")
            before = await self._repository.current_sequence(event.user_id)
            try:
                stored = await self._repository.append(event, self._clock.now())
            except Exception:
                failed += 1
                if self._fail_fast:
                    raise
                continue
            after = await self._repository.current_sequence(event.user_id)
            if after > before:
                inserted += 1
            else:
                skipped += 1
            ranges.setdefault(event.user_id, []).append(stored.sequence)
        return ReplayResult(
            input_count=len(events),
            inserted_count=inserted,
            skipped_count=skipped,
            failed_count=failed,
            user_hashes=tuple(sorted(_safe_hash(value) for value in users)),
            scope_hashes=tuple(sorted(_safe_hash(value) for value in scopes)),
            sequence_ranges=tuple(
                sorted(
                    (_safe_hash(user), min(values), max(values)) for user, values in ranges.items()
                )
            ),
        )


def _safe_hash(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()
