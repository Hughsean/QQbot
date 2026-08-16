"""Pure value transformations used by delegated Microsoft OAuth flows."""

import hashlib


def hash_secret(value: str) -> bytes:
    return hashlib.sha256(value.encode()).digest()


def mask_account(email: str | None) -> str:
    if not email or "@" not in email:
        return "account"
    local, domain = email.split("@", 1)
    return f"{local[:1]}***@{domain}"


def safe_callback(parameters: dict[str, str]) -> dict[str, str]:
    allowed = {"code", "state", "error", "error_description", "error_uri"}
    return {key: value for key, value in parameters.items() if key in allowed}
