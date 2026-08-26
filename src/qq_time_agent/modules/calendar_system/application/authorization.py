"""Calendar-owned authorization policies for trusted internal principals."""

import secrets
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OwnerCalendarAuthorization:
    owner_principal: str

    async def authorize(self, principal: str, operation: str) -> bool:
        del operation
        return secrets.compare_digest(principal, self.owner_principal)
