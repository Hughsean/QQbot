"""Bounded local blob storage using opaque asset-derived paths."""

import asyncio
import hashlib
import os
import re
from pathlib import Path
from uuid import UUID, uuid4

from qq_time_agent.modules.inbox.application.asset_ports import BlobReceipt

_STORAGE_KEY = re.compile(r"^[0-9a-f]{2}/[0-9a-f]{32}$")


class FileAssetBlobStore:
    def __init__(self, root: Path, max_bytes: int) -> None:
        if max_bytes <= 0:
            raise ValueError("asset maximum bytes must be positive")
        self._root = root.resolve()
        self._max_bytes = max_bytes

    async def put(self, asset_id: UUID, content: bytes) -> BlobReceipt:
        if not content or len(content) > self._max_bytes:
            raise ValueError("asset content size is outside the allowed range")
        digest = hashlib.sha256(content).hexdigest()
        key = f"{asset_id.hex[:2]}/{asset_id.hex}"
        path = self._path(key)
        await asyncio.to_thread(_write_atomically, path, content, digest)
        return BlobReceipt(key, len(content), digest)

    async def read(self, storage_key: str) -> bytes:
        content = await asyncio.to_thread(self._path(storage_key).read_bytes)
        if len(content) > self._max_bytes:
            raise ValueError("stored asset exceeds configured maximum")
        return content

    async def delete(self, storage_key: str) -> None:
        await asyncio.to_thread(self._path(storage_key).unlink, missing_ok=True)

    def _path(self, storage_key: str) -> Path:
        if _STORAGE_KEY.fullmatch(storage_key) is None:
            raise ValueError("invalid asset storage key")
        return self._root.joinpath(*storage_key.split("/"))


def _write_atomically(path: Path, content: bytes, digest: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("asset identity cannot be overwritten with different content")
        return
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
