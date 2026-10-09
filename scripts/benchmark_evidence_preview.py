"""Benchmark the source-page preview path before and after the cache changes.

This uses a local in-memory object-store double, so it measures application
work and page-object behavior without requiring production GCS credentials.
Set ``DMEF_BENCH_GCS_DELAY_MS`` and ``DMEF_BENCH_PAGE_DELAY_MS`` to model
source-PDF and page-object download latency.
"""

from __future__ import annotations

import hashlib
import os
import time
from statistics import mean

import fitz

import routes.review as review
import services.evidence_previews as previews
from services.evidence_previews import preview_key
from services.pdf_processor import render_source_page

APPLICATION_ID = 9
STORAGE_KEY = "applications/9/source/benchmark.pdf"
SOURCE_VERSION = "2026-10-07T00:00:00+00:00"


class FakeStore:
    def __init__(self, payload: bytes, source_delay_seconds: float, page_delay_seconds: float) -> None:
        self.payload = payload
        self.source_delay_seconds = source_delay_seconds
        self.page_delay_seconds = page_delay_seconds
        self.objects: dict[str, bytes] = {}
        self.downloads = 0
        self.page_downloads = 0

    def get(self, key: str) -> bytes:
        if key == STORAGE_KEY:
            self.downloads += 1
            if self.source_delay_seconds:
                time.sleep(self.source_delay_seconds)
            return self.payload
        self.page_downloads += 1
        if self.page_delay_seconds:
            time.sleep(self.page_delay_seconds)
        return self.objects[key]


def _pdf_bytes() -> bytes:
    document = fitz.open()
    for page_number in range(8):
        page = document.new_page()
        page.insert_text((72, 72), f"Evidence benchmark page {page_number + 1} " * 20)
    payload = document.tobytes()
    document.close()
    return payload


def _reset_caches() -> None:
    review._PAGE_CACHE.clear()
    review._SOURCE_CACHE.clear()
    review._SOURCE_CACHE_BYTES = 0


def _old_request(store: FakeStore, payload: bytes) -> None:
    digest = hashlib.sha256(store.get(STORAGE_KEY)).hexdigest()
    _ = digest
    render_source_page(payload, 1, dpi=150)


def _new_request() -> None:
    response = review.get_application_source_page(APPLICATION_ID, 1, dpi=150)
    assert response.body.startswith(b"\x89PNG")


def main() -> None:
    payload = _pdf_bytes()
    source_delay_seconds = float(os.getenv("DMEF_BENCH_GCS_DELAY_MS", "50")) / 1000
    page_delay_seconds = float(os.getenv("DMEF_BENCH_PAGE_DELAY_MS", "5")) / 1000
    store = FakeStore(payload, source_delay_seconds, page_delay_seconds)

    import services.storage
    import services.storage.refs

    services.storage.get_store = lambda: store  # type: ignore[assignment]
    source_ref = {
        "storage_key": STORAGE_KEY,
        "created_at": SOURCE_VERSION,
        "size_bytes": len(payload),
    }
    services.storage.refs.get_ref = lambda owner_table, owner_id, purpose: source_ref  # type: ignore[assignment]
    previews.get_ref = lambda owner_table, owner_id, purpose: source_ref  # type: ignore[assignment]
    review.load_latest_uploaded_file = lambda application_id: {  # type: ignore[assignment]
        "original_filename": "benchmark.pdf"
    }

    previews_key = preview_key(APPLICATION_ID, SOURCE_VERSION, 1)
    store.objects[previews_key] = render_source_page(payload, 1, dpi=150)

    samples = 5
    old_times: list[float] = []
    store.downloads = 0
    for _ in range(samples):
        started = time.perf_counter()
        _old_request(store, payload)
        old_times.append(time.perf_counter() - started)
    old_downloads = store.downloads

    _reset_caches()
    store.downloads = 0
    store.page_downloads = 0
    new_times: list[float] = []
    for _ in range(samples):
        started = time.perf_counter()
        _new_request()
        new_times.append(time.perf_counter() - started)
    new_downloads = store.downloads

    print(f"PDF bytes: {len(payload):,}")
    print(f"Page preview bytes: {len(store.objects[previews_key]):,}")
    print(f"Simulated source download: {source_delay_seconds * 1000:.1f} ms")
    print(f"Simulated page download: {page_delay_seconds * 1000:.1f} ms")
    print(f"Before: mean={mean(old_times) * 1000:.1f} ms, downloads={old_downloads}")
    print(
        f"After:  mean={mean(new_times) * 1000:.1f} ms, "
        f"source_downloads={new_downloads}, page_downloads={store.page_downloads}"
    )
    print(f"After first request: {new_times[0] * 1000:.1f} ms")
    print(f"After warm request:  {mean(new_times[1:]) * 1000:.1f} ms")


if __name__ == "__main__":
    main()
