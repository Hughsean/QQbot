"""Immutable configured preferences for the one-owner MVP."""

from qq_time_agent.modules.identity.application.ports import UserPreferencesRepository
from qq_time_agent.modules.identity.contracts import UserPreferencesView


class UserPreferencesService:
    def __init__(
        self, repository: UserPreferencesRepository, defaults: UserPreferencesView
    ) -> None:
        self._repository = repository
        self._defaults = defaults

    async def get_preferences(self, user_id: str) -> UserPreferencesView:
        if user_id != self._defaults.user_id:
            raise LookupError("user preferences do not exist")
        value = await self._repository.get(user_id)
        return value or await self._repository.initialize(self._defaults)
