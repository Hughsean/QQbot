"""Opaque, bounded QQ Mail UID cursor."""

import json
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ImapCursor:
    uidvalidity: int
    last_uid: int

    def encode(self) -> str:
        return json.dumps(
            {"last_uid": self.last_uid, "uidvalidity": self.uidvalidity, "version": 1},
            separators=(",", ":"),
            sort_keys=True,
        )

    @classmethod
    def decode(cls, value: str | None) -> "ImapCursor | None":
        if value is None:
            return None
        try:
            payload = json.loads(value)
            if payload["version"] != 1:
                raise ValueError
            uidvalidity = int(payload["uidvalidity"])
            last_uid = int(payload["last_uid"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("invalid QQ Mail cursor") from exc
        if uidvalidity < 1 or last_uid < 0:
            raise ValueError("invalid QQ Mail cursor")
        return cls(uidvalidity, last_uid)
