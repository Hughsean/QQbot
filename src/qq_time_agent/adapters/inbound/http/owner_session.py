"""Short-lived signed single-owner browser sessions and CSRF verification."""

import base64
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import timedelta

from pydantic import SecretStr

from qq_time_agent.contracts.clock import Clock


class OwnerAuthenticationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class OwnerSession:
    user_id: str
    expires_at_epoch: int


class OwnerSessionSigner:
    def __init__(self, signing_key: SecretStr, clock: Clock) -> None:
        key = signing_key.get_secret_value().encode()
        if len(key) < 32:
            raise ValueError("APP_SIGNING_KEY must contain at least 32 bytes")
        self._key = key
        self._clock = clock

    def issue(self, user_id: str, lifetime: timedelta = timedelta(minutes=15)) -> str:
        if not user_id or lifetime <= timedelta(0) or lifetime > timedelta(hours=1):
            raise ValueError("valid user and session lifetime are required")
        payload = {
            "sub": user_id,
            "exp": int((self._clock.now() + lifetime).timestamp()),
            "jti": secrets.token_urlsafe(16),
        }
        encoded = _encode(json.dumps(payload, separators=(",", ":")).encode())
        signature = _encode(hmac.digest(self._key, encoded.encode(), "sha256"))
        return f"{encoded}.{signature}"

    def verify(self, token: str) -> OwnerSession:
        try:
            encoded, supplied = token.split(".", 1)
            expected = _encode(hmac.digest(self._key, encoded.encode(), "sha256"))
            if not hmac.compare_digest(supplied, expected):
                raise OwnerAuthenticationError("owner session signature is invalid")
            payload = json.loads(_decode(encoded))
            user_id = str(payload["sub"])
            expires = int(payload["exp"])
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise OwnerAuthenticationError("owner session is invalid") from exc
        if int(self._clock.now().timestamp()) >= expires:
            raise OwnerAuthenticationError("owner session has expired")
        return OwnerSession(user_id, expires)


def verify_csrf(cookie: str | None, header: str | None) -> None:
    if not cookie or not header or not hmac.compare_digest(cookie, header):
        raise OwnerAuthenticationError("CSRF verification failed")


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
