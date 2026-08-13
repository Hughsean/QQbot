"""Envelope-encrypted Credential Vault use case."""

from datetime import datetime
from uuid import uuid4

from qq_time_agent.contracts.clock import Clock
from qq_time_agent.modules.credentials.application.ports import (
    CredentialCipher,
    CredentialRepository,
    EncryptedCredential,
)
from qq_time_agent.modules.credentials.contracts import (
    CredentialHandle,
    CredentialKind,
    CredentialRef,
)


class CredentialNotFoundError(LookupError):
    pass


class VaultService:
    def __init__(
        self, repository: CredentialRepository, cipher: CredentialCipher, clock: Clock
    ) -> None:
        self._repository = repository
        self._cipher = cipher
        self._clock = clock

    async def store(
        self, material: str, kind: CredentialKind, expires_at: datetime | None = None
    ) -> CredentialRef:
        if not material:
            raise ValueError("credential material is required")
        now = self._clock.now()
        _require_aware(now)
        if expires_at is not None:
            _require_aware(expires_at)
            if expires_at <= now:
                raise ValueError("credential expiration must be in the future")
        credential_id = uuid4()
        nonce, ciphertext = self._cipher.encrypt(credential_id, kind, material)
        record = EncryptedCredential(
            credential_id,
            kind,
            self._cipher.key_version,
            nonce,
            ciphertext,
            now,
            expires_at,
        )
        await self._repository.add(record)
        return CredentialRef(credential_id)

    async def open(self, reference: CredentialRef) -> CredentialHandle:
        record = await self._repository.get(reference.credential_id)
        if record is None:
            raise CredentialNotFoundError("credential does not exist")
        now = self._clock.now()
        if record.expires_at is not None and now >= record.expires_at:
            raise CredentialNotFoundError("credential has expired")
        material = self._cipher.decrypt(record)
        return CredentialHandle(material, record.kind, record.expires_at)

    async def delete(self, reference: CredentialRef) -> bool:
        return await self._repository.delete(reference.credential_id)

    async def replace(self, reference: CredentialRef, material: str) -> None:
        if not material:
            raise ValueError("credential material is required")
        current = await self._repository.get(reference.credential_id)
        if current is None:
            raise CredentialNotFoundError("credential does not exist")
        nonce, ciphertext = self._cipher.encrypt(current.credential_id, current.kind, material)
        replacement = EncryptedCredential(
            current.credential_id,
            current.kind,
            self._cipher.key_version,
            nonce,
            ciphertext,
            self._clock.now(),
            current.expires_at,
        )
        if not await self._repository.replace(replacement):
            raise CredentialNotFoundError("credential disappeared during replacement")


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timezone-aware datetime required")
