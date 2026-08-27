from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from qq_time_agent.modules.identity.application.aliases import OwnerGroupAliasService
from qq_time_agent.modules.identity.application.tools import OwnerGroupAliasToolRegistry
from qq_time_agent.modules.identity.contracts import OwnerGroupAlias

NOW = datetime(2026, 8, 27, tzinfo=UTC)


class Clock:
    def now(self) -> datetime:
        return NOW


@dataclass
class Repository:
    values: dict[str, OwnerGroupAlias] = field(default_factory=dict)

    async def list(self, user_id: str) -> tuple[OwnerGroupAlias, ...]:
        assert user_id == "owner"
        return tuple(sorted(self.values.values(), key=lambda item: item.alias))

    async def add_or_get(
        self, user_id: str, alias: OwnerGroupAlias, normalized_alias: str, now: datetime
    ) -> OwnerGroupAlias:
        assert user_id == "owner" and now == NOW
        return self.values.setdefault(normalized_alias, alias)


@pytest.mark.asyncio
async def test_owner_group_alias_is_normalized_and_idempotent() -> None:
    service = OwnerGroupAliasService(Repository(), Clock())
    assert await service.register_owner_group_alias("owner", "  风拾一  ") == OwnerGroupAlias(
        "风拾一"
    )
    assert await service.register_owner_group_alias("owner", "风拾一") == OwnerGroupAlias("风拾一")
    assert await service.list_owner_group_aliases("owner") == (OwnerGroupAlias("风拾一"),)


@pytest.mark.asyncio
async def test_owner_group_alias_rejects_non_owner_and_invalid_tool_requests() -> None:
    service = OwnerGroupAliasService(Repository(), Clock())
    with pytest.raises(PermissionError):
        await service.register_owner_group_alias("intruder", "风拾一")
    tools = OwnerGroupAliasToolRegistry(service)
    assert await tools.call("owner", "register_owner_group_alias", {"alias": "风拾一"}) == {
        "alias": "风拾一",
        "status": "REGISTERED",
    }
    with pytest.raises(ValueError):
        await tools.call("owner", "register_owner_group_alias", {"alias": "风拾一", "extra": "x"})
