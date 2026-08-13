"""Internal persistence and encryption ports for Credential Vault."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from qq_time_agent.modules.credentials.contracts import CredentialKind


@dataclass(frozen=True, slots=True)
class EncryptedCredential:
    credential_id: UUID
    kind: CredentialKind
    key_version: int
    nonce: bytes
    ciphertext: bytes
    created_at: datetime
    expires_at: datetime | None


class CredentialCipher(Protocol):
    key_version: int

    def encrypt(
        self, credential_id: UUID, kind: CredentialKind, plaintext: str
    ) -> tuple[bytes, bytes]: ...

    def decrypt(self, credential: EncryptedCredential) -> str: ...


class CredentialRepository(Protocol):
    async def add(self, credential: EncryptedCredential) -> None: ...

    async def get(self, credential_id: UUID) -> EncryptedCredential | None: ...

    async def replace(self, credential: EncryptedCredential) -> bool: ...

    async def delete(self, credential_id: UUID) -> bool: ...
