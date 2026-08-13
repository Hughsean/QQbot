"""AES-256-GCM envelope encryption with explicit key version and AAD."""

import base64
import secrets
from uuid import UUID

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import SecretStr

from qq_time_agent.modules.credentials.application.ports import EncryptedCredential
from qq_time_agent.modules.credentials.contracts import CredentialKind


class AesGcmCredentialCipher:
    key_version = 1

    def __init__(self, encoded_key: SecretStr) -> None:
        self._key = _decode_key(encoded_key.get_secret_value())
        self._cipher = AESGCM(self._key)

    def encrypt(
        self, credential_id: UUID, kind: CredentialKind, plaintext: str
    ) -> tuple[bytes, bytes]:
        nonce = secrets.token_bytes(12)
        ciphertext = self._cipher.encrypt(
            nonce, plaintext.encode("utf-8"), _aad(credential_id, kind, self.key_version)
        )
        return nonce, ciphertext

    def decrypt(self, credential: EncryptedCredential) -> str:
        if credential.key_version != self.key_version:
            raise ValueError("unsupported credential key version")
        plaintext = self._cipher.decrypt(
            credential.nonce,
            credential.ciphertext,
            _aad(credential.credential_id, credential.kind, credential.key_version),
        )
        return plaintext.decode("utf-8")


def _decode_key(value: str) -> bytes:
    candidates = (value, value + "=" * (-len(value) % 4))
    for candidate in candidates:
        try:
            key = base64.urlsafe_b64decode(candidate.encode("ascii"))
        except (ValueError, UnicodeEncodeError):
            continue
        if len(key) == 32:
            return key
    if len(value.encode("utf-8")) == 32:
        return value.encode("utf-8")
    raise ValueError("CREDENTIAL_ENCRYPTION_KEY must encode exactly 32 bytes")


def _aad(credential_id: UUID, kind: CredentialKind, key_version: int) -> bytes:
    return f"{credential_id}:{kind.value}:{key_version}".encode()
