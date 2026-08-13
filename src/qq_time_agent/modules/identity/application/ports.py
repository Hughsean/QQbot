"""Private Identity preferences persistence port."""

from typing import Protocol

from qq_time_agent.modules.identity.contracts import UserPreferencesView


class UserPreferencesRepository(Protocol):
    async def get(self, user_id: str) -> UserPreferencesView | None: ...

    async def initialize(self, preferences: UserPreferencesView) -> UserPreferencesView: ...
