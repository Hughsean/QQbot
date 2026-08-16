"""Provider-neutral account identity fingerprint contract."""

from typing import Protocol


class AccountFingerprinter(Protocol):
    def fingerprint(self, provider: str, canonical_identity: str) -> str: ...
