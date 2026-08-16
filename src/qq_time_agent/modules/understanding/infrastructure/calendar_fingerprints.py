"""HMAC calendar identities that never persist raw provider UIDs."""

import hashlib
import hmac

from pydantic import SecretStr


class HmacCalendarEventFingerprinter:
    def __init__(self, key: SecretStr) -> None:
        raw = key.get_secret_value().encode()
        if len(raw) < 16:
            raise ValueError("calendar fingerprint key is too short")
        self._key = hmac.digest(raw, b"calendar-event-fingerprint-v1", "sha256")

    def event_key(self, uid: str, recurrence_id: str | None) -> str:
        if not uid.strip():
            raise ValueError("calendar UID is required")
        basis = uid.strip().encode() + b"\x00" + (recurrence_id or "").encode()
        return hmac.new(self._key, basis, hashlib.sha256).hexdigest()

    def version_key(self, event_key: str, sequence: int) -> str:
        if len(event_key) != 64 or sequence < 0:
            raise ValueError("invalid calendar event version")
        basis = f"{event_key}:{sequence}".encode()
        return hmac.new(self._key, basis, hashlib.sha256).hexdigest()
