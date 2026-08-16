"""Keyed account identity fingerprinting without exposing account identifiers."""

import hashlib
import hmac

from pydantic import SecretStr


class HmacAccountFingerprinter:
    def __init__(self, secret: SecretStr) -> None:
        material = secret.get_secret_value().encode()
        self._key = hashlib.sha256(b"account-fingerprint-v1|" + material).digest()

    def fingerprint(self, provider: str, canonical_identity: str) -> str:
        identity = canonical_identity.strip()
        if not provider.strip() or not identity:
            raise ValueError("provider and canonical identity are required")
        payload = f"v1|{provider}|{identity}".encode()
        return "v1:" + hmac.new(self._key, payload, hashlib.sha256).hexdigest()
