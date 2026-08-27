"""Public owner group-chat display-name contracts."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class OwnerGroupAlias:
    alias: str

    def __post_init__(self) -> None:
        if not self.alias.strip() or len(self.alias) > 64:
            raise ValueError("owner group alias is invalid")


class OwnerGroupAliasQueryPort(Protocol):
    async def list_owner_group_aliases(self, user_id: str) -> tuple[OwnerGroupAlias, ...]: ...


class OwnerGroupAliasCommandPort(Protocol):
    async def register_owner_group_alias(self, user_id: str, alias: str) -> OwnerGroupAlias: ...
