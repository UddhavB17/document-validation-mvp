"""Shared ZIP mechanics used by mapped single and batch uploads."""

from __future__ import annotations

import json
from io import BytesIO
from zipfile import ZipFile

import pytest

from services.mapped_zip import extract_mapped_zip


def _archive_bytes() -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("__MACOSX/._loan.pdf", b"ignored")
        archive.writestr("docs/loan.pdf", b"loan-pdf")
        archive.writestr("docs/manifest.json", '{"pdf_file":"docs/loan.pdf"}')
    return buffer.getvalue()


def test_mapped_zip_filters_noise_and_selects_pdf_through_shared_policies():
    result = extract_mapped_zip(
        _archive_bytes(),
        manifest_override=None,
        read_member=lambda archive, member: archive.read(member),
        decode_manifest=json.loads,
        select_pdf=lambda members, manifest: next(
            member for member in members if member.filename == manifest["pdf_file"]
        ),
    )

    assert result.manifest_text == '{"pdf_file":"docs/loan.pdf"}'
    assert result.original_filename == "loan.pdf"
    assert result.pdf_bytes == b"loan-pdf"


def test_mapped_zip_allows_pasted_manifest_to_select_pdf():
    result = extract_mapped_zip(
        _archive_bytes(),
        manifest_override='{"pdf_file":"docs/loan.pdf"}',
        read_member=lambda archive, member: archive.read(member),
        decode_manifest=json.loads,
        select_pdf=lambda members, manifest: next(
            member for member in members if member.filename == manifest["pdf_file"]
        ),
    )
    assert result.pdf_bytes == b"loan-pdf"


def test_mapped_zip_requires_one_manifest_without_override():
    archive = BytesIO()
    with ZipFile(archive, "w") as zipped:
        zipped.writestr("loan.pdf", b"loan")
        zipped.writestr("one.json", "{}")
        zipped.writestr("two.json", "{}")

    with pytest.raises(ValueError, match="exactly one JSON manifest"):
        extract_mapped_zip(
            archive.getvalue(),
            manifest_override=None,
            read_member=lambda source, member: source.read(member),
            decode_manifest=lambda raw: {},
            select_pdf=lambda members, manifest: members[0],
        )
