"""Compressed inputs and sidecars obey the same byte budget as plain PDFs."""

import asyncio
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from fastapi import HTTPException, UploadFile

from routes import upload


@pytest.mark.parametrize("batch", [False, True])
@pytest.mark.parametrize("oversized_member", ["source.pdf", "manifest.json"])
def test_mapped_zip_rejects_oversized_members_before_decompression(
    monkeypatch, batch, oversized_member
):
    limit = 1024
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        for name, content in {
            "source.pdf": b"%PDF-1.4",
            "manifest.json": b'{"pdf_file":"source.pdf"}',
        }.items():
            archive.writestr(name, b"x" * (limit * 4) if name == oversized_member else content)
    assert len(buffer.getvalue()) < limit
    original_open = ZipFile.open

    def guarded_open(archive, member, *args, **kwargs):
        assert member.file_size <= limit, "Oversized ZIP member must not be decompressed"
        return original_open(archive, member, *args, **kwargs)

    monkeypatch.setattr(upload, "max_file_size_bytes", lambda: limit)
    monkeypatch.setattr(ZipFile, "open", guarded_open)
    item = UploadFile(file=BytesIO(buffer.getvalue()), filename="mapped.zip")
    operation = (
        upload._batch_single_mapped_zip(item, "batch-id", "timestamp", "Normal Case")
        if batch
        else upload._save_mapped_zip_package(item, None, "timestamp")
    )
    with pytest.raises(HTTPException, match="File too large") as error:
        asyncio.run(operation)
    assert error.value.status_code == 400


def test_batch_sidecar_read_is_bounded_and_rejects_oversized_input(monkeypatch):
    class BoundedInput(BytesIO):
        def read(self, size=-1):
            assert 0 <= size <= 1024 * 1024, "Sidecars must use bounded reads"
            return super().read(size)

    monkeypatch.setattr(upload, "max_file_size_bytes", lambda: 1024)
    sidecar = UploadFile(
        file=BoundedInput(b"x" * 1025), filename="source.manifest.json"
    )
    with pytest.raises(HTTPException, match="File too large") as error:
        asyncio.run(upload.upload_batch(files=[sidecar]))
    assert error.value.status_code == 400
