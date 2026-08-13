"""Non-serializable, provider-neutral Credential Vault contract."""

from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID


class CredentialKind(StrEnum):
    OAUTH_FLOW = "OAUTH_FLOW"
    REFRESH_TOKEN = "REFRESH_TOKEN"  # noqa: S105 - enum label, not a credential
    ACCESS_TOKEN = "ACCESS_TOKEN"  # noqa: S105 - enum label, not a credential


class CredentialRef:
    __slots__ = ("credential_id",)

    def __init__(self, credential_id: UUID) -> None:
        self.credential_id = credential_id

    def __repr__(self) -> str:
        return f"CredentialRef({self.credential_id})"


class CredentialHandle:
    __slots__ = ("_material", "expires_at", "kind")

    def __init__(self, material: str, kind: CredentialKind, expires_at: datetime | None) -> None:
        self._material = material
        self.kind = kind
        self.expires_at = expires_at

    def reveal(self, now: datetime) -> str:
        if self.expires_at is not None and now >= self.expires_at:
            raise ValueError("credential handle has expired")
        return self._material

    def __repr__(self) -> str:
        return f"CredentialHandle(kind={self.kind.value}, material=[REDACTED])"

    def __reduce__(self) -> str | tuple[object, ...]:
        raise TypeError("CredentialHandle cannot be serialized")


class CredentialVault(Protocol):
    async def store(
        self, material: str, kind: CredentialKind, expires_at: datetime | None = None
    ) -> CredentialRef: ...

    async def open(self, reference: CredentialRef) -> CredentialHandle: ...

    async def replace(self, reference: CredentialRef, material: str) -> None: ...

    async def delete(self, reference: CredentialRef) -> bool: ...
