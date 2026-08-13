import base64
import pickle
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from pydantic import SecretStr

from qq_time_agent.modules.credentials.application.ports import EncryptedCredential
from qq_time_agent.modules.credentials.application.vault import (
    CredentialNotFoundError,
    VaultService,
)
from qq_time_agent.modules.credentials.contracts import CredentialKind
from qq_time_agent.modules.credentials.infrastructure.cipher import AesGcmCredentialCipher


@dataclass
class FixedClock:
    value: datetime

    def now(self) -> datetime:
        return self.value


@dataclass
class MemoryRepository:
    records: dict[UUID, EncryptedCredential] = field(default_factory=dict)
    reject_replace: bool = False

    async def add(self, credential: EncryptedCredential) -> None:
        self.records[credential.credential_id] = credential

    async def get(self, credential_id: UUID) -> EncryptedCredential | None:
        return self.records.get(credential_id)

    async def replace(self, credential: EncryptedCredential) -> bool:
        if self.reject_replace or credential.credential_id not in self.records:
            return False
        self.records[credential.credential_id] = credential
        return True

    async def delete(self, credential_id: UUID) -> bool:
        return self.records.pop(credential_id, None) is not None


def _vault() -> tuple[VaultService, MemoryRepository, FixedClock]:
    key = base64.urlsafe_b64encode(b"k" * 32).decode()
    repository = MemoryRepository()
    clock = FixedClock(datetime(2026, 8, 13, tzinfo=UTC))
    vault = VaultService(repository, AesGcmCredentialCipher(SecretStr(key)), clock)
    return vault, repository, clock


@pytest.mark.asyncio
async def test_vault_encrypts_opens_rotates_and_deletes_secret() -> None:
    vault, repository, clock = _vault()
    reference = await vault.store("refresh-token-one", CredentialKind.REFRESH_TOKEN)
    stored = repository.records[reference.credential_id]
    assert b"refresh-token-one" not in stored.ciphertext
    handle = await vault.open(reference)
    assert handle.reveal(clock.now()) == "refresh-token-one"
    assert "refresh-token-one" not in repr(handle)
    with pytest.raises(TypeError, match="cannot be serialized"):
        pickle.dumps(handle)

    await vault.replace(reference, "refresh-token-two")
    rotated = await vault.open(reference)
    assert rotated.reveal(clock.now()) == "refresh-token-two"
    assert await vault.delete(reference)
    with pytest.raises(CredentialNotFoundError):
        await vault.open(reference)


@pytest.mark.asyncio
async def test_vault_enforces_expiration_and_timezone() -> None:
    vault, _, clock = _vault()
    expires = clock.now() + timedelta(minutes=1)
    reference = await vault.store("flow", CredentialKind.OAUTH_FLOW, expires)
    clock.value = expires
    with pytest.raises(CredentialNotFoundError, match="expired"):
        await vault.open(reference)
    with pytest.raises(ValueError, match="future"):
        await vault.store("flow", CredentialKind.OAUTH_FLOW, expires)
    with pytest.raises(ValueError, match="timezone-aware"):
        await vault.store("flow", CredentialKind.OAUTH_FLOW, datetime(2026, 8, 14))


@pytest.mark.asyncio
async def test_vault_rejects_empty_or_missing_replacement() -> None:
    vault, repository, _ = _vault()
    with pytest.raises(ValueError, match="material is required"):
        await vault.store("", CredentialKind.REFRESH_TOKEN)
    missing = await vault.store("temporary", CredentialKind.REFRESH_TOKEN)
    await vault.delete(missing)
    with pytest.raises(CredentialNotFoundError, match="does not exist"):
        await vault.replace(missing, "replacement")
    existing = await vault.store("original", CredentialKind.REFRESH_TOKEN)
    with pytest.raises(ValueError, match="material is required"):
        await vault.replace(existing, "")
    repository.reject_replace = True
    with pytest.raises(CredentialNotFoundError, match="disappeared"):
        await vault.replace(existing, "replacement")


def test_cipher_rejects_invalid_key_and_tampered_aad() -> None:
    with pytest.raises(ValueError, match="32 bytes"):
        AesGcmCredentialCipher(SecretStr("too-short"))
