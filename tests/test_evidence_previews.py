from pathlib import Path

import fitz

import services.evidence_previews as previews


def test_generate_application_page_previews_uploads_each_page(tmp_path: Path, monkeypatch) -> None:
    source_path = tmp_path / "source.pdf"
    document = fitz.open()
    for number in range(2):
        page = document.new_page()
        page.insert_text((72, 72), f"Page {number + 1}")
    document.save(source_path)
    document.close()

    uploaded: dict[str, bytes] = {}
    refs: list[dict[str, object]] = []

    class _Store:
        def put(self, key: str, data: bytes, content_type: str) -> str:
            assert content_type == "image/png"
            uploaded[key] = bytes(data)
            return key

    monkeypatch.setattr(
        previews,
        "get_ref",
        lambda owner_table, owner_id, purpose: {
            "storage_key": "applications/9/source/source.pdf",
            "created_at": "2026-10-07T00:00:00+00:00",
        },
    )
    monkeypatch.setattr(previews, "get_store", lambda: _Store())
    monkeypatch.setattr(
        previews,
        "record_ref",
        lambda owner_table, owner_id, purpose, key, **kwargs: refs.append(
            {"purpose": purpose, "key": key, **kwargs}
        ),
    )

    assert previews.generate_application_page_previews(source_path, 9) == 2
    assert sorted(uploaded) == [
        previews.preview_key(9, "2026-10-07T00:00:00+00:00", 1),
        previews.preview_key(9, "2026-10-07T00:00:00+00:00", 2),
    ]
    assert all(payload.startswith(b"\x89PNG") for payload in uploaded.values())
    assert [ref["purpose"] for ref in refs] == ["page_preview", "page_preview"]
