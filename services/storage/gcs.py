"""Google Cloud Storage backend.

Uses Application Default Credentials; ``signed_url`` issues V4 signed URLs.
When ``DMEF_GCS_BUCKET`` is unset the backend cannot operate and every
method raises ``NotImplementedError``.
"""

from __future__ import annotations

from datetime import timedelta
from typing import BinaryIO

from services.storage._keys import check_key, check_prefix


class GcsObjectStore:
    """GCS-backed store selected with ``DMEF_STORAGE_BACKEND=gcs``."""

    def __init__(self, bucket: str | None = None) -> None:
        from services.paths import gcs_bucket

        raw = bucket if bucket is not None else gcs_bucket()
        self.bucket = raw.strip()

    def _require_bucket(self) -> str:
        if not self.bucket:
            raise NotImplementedError("GcsObjectStore requires DMEF_GCS_BUCKET to be configured")
        return self.bucket

    def _client(self):  # type: ignore[no-untyped-def]
        from google.cloud import storage

        return storage.Client()

    def _blob(self, key: str):  # type: ignore[no-untyped-def]
        check_key(key)
        # Fail fast when unconfigured so callers never touch ADC by accident.
        self._require_bucket()
        client = self._client()
        return client.bucket(self.bucket).blob(key)

    def put(self, key: str, data: bytes | BinaryIO, content_type: str) -> str:
        blob = self._blob(key)
        payload = data.read() if hasattr(data, "read") else data
        blob.upload_from_string(
            bytes(payload), content_type=content_type or "application/octet-stream"
        )
        return key

    def get(self, key: str) -> bytes:
        from google.api_core.exceptions import NotFound

        try:
            return bytes(self._blob(key).download_as_bytes())
        except NotFound as exc:
            raise FileNotFoundError(f"Object not found: {key!r}") from exc

    def open(self, key: str) -> BinaryIO:
        from google.api_core.exceptions import NotFound

        try:
            return self._blob(key).open("rb")
        except NotFound as exc:
            raise FileNotFoundError(f"Object not found: {key!r}") from exc

    def exists(self, key: str) -> bool:
        return bool(self._blob(key).exists())

    def delete(self, key: str) -> None:
        from google.api_core.exceptions import NotFound

        try:
            self._blob(key).delete()
        except NotFound:
            pass

    def signed_url(self, key: str, expires_seconds: int = 600) -> str:
        return str(
            self._blob(key).generate_signed_url(
                version="v4",
                expiration=timedelta(seconds=expires_seconds),
                method="GET",
            )
        )

    def list(self, prefix: str) -> list[str]:
        check_prefix(prefix)
        self._require_bucket()
        client = self._client()
        blobs = client.list_blobs(self.bucket, prefix=prefix)
        return sorted(blob.name for blob in blobs)
