"""Object storage abstraction.

Keys are always relative. Keys containing ``..`` or starting with ``/`` are
rejected.
"""

from __future__ import annotations

from pathlib import Path
from typing import BinaryIO, Protocol

from services.paths import local_store_dir, storage_backend
from services.storage._keys import check_key, check_prefix
from services.storage.gcs import GcsObjectStore

__all__ = [
    "GcsObjectStore",
    "LocalObjectStore",
    "ObjectStore",
    "get_store",
]


class ObjectStore(Protocol):
    """Storage backend contract from ``docs/agents/00-CONTRACTS.md`` §2."""

    def put(self, key: str, data: bytes | BinaryIO, content_type: str) -> str: ...
    def get(self, key: str) -> bytes: ...
    def open(self, key: str) -> BinaryIO: ...  # streaming read
    def exists(self, key: str) -> bool: ...
    def delete(self, key: str) -> None: ...
    def signed_url(self, key: str, expires_seconds: int = 600) -> str: ...
    def list(self, prefix: str) -> list[str]: ...


class LocalObjectStore:
    """Filesystem-backed store under ``DMEF_LOCAL_STORE_DIR``."""

    def __init__(self, base_dir: Path | str | None = None) -> None:
        self.base_dir = Path(base_dir) if base_dir is not None else local_store_dir()

    def _path(self, key: str) -> Path:
        check_key(key)
        return self.base_dir / key

    def put(
        self,
        key: str,
        data: bytes | BinaryIO,
        content_type: str = "application/octet-stream",
    ) -> str:
        _ = content_type  # local backend stores raw bytes; type is metadata only
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = data.read() if hasattr(data, "read") else data
        path.write_bytes(bytes(payload))
        return key

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def open(self, key: str) -> BinaryIO:
        return self._path(key).open("rb")

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def signed_url(self, key: str, expires_seconds: int = 600) -> str:
        _ = expires_seconds  # local URLs are served by the app; no expiry signing
        check_key(key)
        return f"/storage/{key}"

    def list(self, prefix: str) -> list[str]:
        check_prefix(prefix)
        if not self.base_dir.is_dir():
            return []
        keys = [
            path.relative_to(self.base_dir).as_posix()
            for path in self.base_dir.rglob("*")
            if path.is_file()
        ]
        return sorted(key for key in keys if key.startswith(prefix))


def get_store() -> ObjectStore:
    """Return the configured store (``DMEF_STORAGE_BACKEND=local|gcs``)."""
    backend = storage_backend()
    if backend == "local":
        return LocalObjectStore()
    if backend == "gcs":
        return GcsObjectStore()
    raise ValueError(f"Unknown DMEF_STORAGE_BACKEND: {backend!r}")
