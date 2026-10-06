"""Resilient ZIP intake uploads on flaky uplinks (tmp/user-portal-ux)."""

import time

from fastapi.testclient import TestClient

import database.db as db
import routes.upload as upload_route
from database.db import init_db
from main import app
from services.storage.gcs import GcsObjectStore


class _FlakyStore:
    """Object store stub failing a set number of times, then succeeding."""

    def __init__(self, failures: int, error: Exception | None = None) -> None:
        self.failures = failures
        self.error = error or ConnectionError("uplink stalled")
        self.calls = 0

    def put(self, key: str, data, content_type: str) -> str:
        self.calls += 1
        if self.calls <= self.failures:
            raise self.error
        return key


def test_store_bytes_retries_transient_then_succeeds(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "dmef.db")
    init_db()
    store = _FlakyStore(failures=2)
    monkeypatch.setattr(upload_route, "get_store", lambda: store)
    slept: list[float] = []
    monkeypatch.setattr(time, "sleep", slept.append)

    upload_route._store_bytes("intake/x/source.zip", b"zip-bytes", "application/zip")

    assert store.calls == 3
    assert slept == [2.0, 6.0]


def test_store_bytes_raises_after_exhaustion(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "dmef.db")
    init_db()
    store = _FlakyStore(failures=99)
    monkeypatch.setattr(upload_route, "get_store", lambda: store)
    monkeypatch.setattr(time, "sleep", lambda seconds: None)

    try:
        upload_route._store_bytes("intake/x/source.zip", b"zip-bytes", "application/zip")
    except ConnectionError:
        pass
    else:  # pragma: no cover - must raise
        raise AssertionError("expected ConnectionError after retries")
    assert store.calls == 3


def test_failed_preparation_row_served_as_failed(tmp_path, monkeypatch, auth_headers) -> None:
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "dmef.db")
    init_db()
    package_id = "a" * 32
    upload_route._persist_intake_failure(
        package_id, "loan.zip", RuntimeError("uplink stalled"), total_files=4, total_pages=120
    )
    client = TestClient(app)

    response = client.get(f"/upload/package/{package_id}/preparation", headers=auth_headers)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "failed"
    assert payload["stage"] == "failed"
    assert "uplink stalled" in str(payload["error"])


def test_gcs_put_uses_small_resumable_chunks() -> None:
    seen: dict = {}

    class _FakeBlob:
        chunk_size = None

        def upload_from_string(self, payload: bytes, content_type: str | None = None) -> None:
            seen["bytes"] = bytes(payload)
            seen["content_type"] = content_type
            seen["chunk_size"] = self.chunk_size

    store = GcsObjectStore.__new__(GcsObjectStore)
    store._blob = lambda key: _FakeBlob()  # noqa: SLF001 - seam for chunk-size assertion

    assert store.put("k", b"0123456789", "application/zip") == "k"
    assert seen["bytes"] == b"0123456789"
    assert seen["chunk_size"] == 5 * 1024 * 1024
    assert seen["chunk_size"] % (256 * 1024) == 0
