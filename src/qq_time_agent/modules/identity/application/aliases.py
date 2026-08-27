"""Owner-scoped group-chat display-name registration."""

from qq_time_agent.contracts.clock import Clock
from qq_time_agent.modules.identity.application.ports import OwnerGroupAliasRepository
from qq_time_agent.modules.identity.contracts import OwnerGroupAlias


class OwnerGroupAliasService:
    def __init__(
        self, repository: OwnerGroupAliasRepository, clock: Clock, owner_id: str = "owner"
    ) -> None:
        if not owner_id.strip():
            raise ValueError("owner identity is required")
        self._repository = repository
        self._clock = clock
        self._owner_id = owner_id

    async def list_owner_group_aliases(self, user_id: str) -> tuple[OwnerGroupAlias, ...]:
        self._authorize(user_id)
        return await self._repository.list(user_id)

    async def register_owner_group_alias(self, user_id: str, alias: str) -> OwnerGroupAlias:
        self._authorize(user_id)
        value = OwnerGroupAlias(" ".join(alias.split()))
        return await self._repository.add_or_get(
            user_id, value, value.alias.casefold(), self._clock.now()
        )

    def _authorize(self, user_id: str) -> None:
        if user_id != self._owner_id:
            raise PermissionError("owner identity alias is not authorized")
