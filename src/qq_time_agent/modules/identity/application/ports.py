"""Private Identity persistence ports."""

from datetime import datetime
from typing import Protocol

from qq_time_agent.modules.identity.contracts import OwnerGroupAlias, UserPreferencesView


class UserPreferencesRepository(Protocol):
    async def get(self, user_id: str) -> UserPreferencesView | None: ...

    async def initialize(self, preferences: UserPreferencesView) -> UserPreferencesView: ...


class OwnerGroupAliasRepository(Protocol):
    async def list(self, user_id: str) -> tuple[OwnerGroupAlias, ...]: ...

    async def add_or_get(
        self, user_id: str, alias: OwnerGroupAlias, normalized_alias: str, now: datetime
    ) -> OwnerGroupAlias: ...
