"""Shared archive mechanics for manifest-driven ZIP uploads."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePosixPath
from zipfile import ZipFile, ZipInfo


@dataclass(frozen=True)
class MappedZipContent:
    manifest_text: str
    original_filename: str
    pdf_bytes: bytes


def extract_mapped_zip(
    package_bytes: bytes,
    *,
    manifest_override: str | None,
    read_member: Callable[[ZipFile, ZipInfo], bytes],
    decode_manifest: Callable[[str], dict[str, object]],
    select_pdf: Callable[[list[ZipInfo], dict[str, object]], ZipInfo],
) -> MappedZipContent:
    """Apply shared member filtering and manifest-to-PDF selection.

    Route-specific bounded member reads, manifest validation, and user-facing
    errors are injected by the caller so the service owns archive mechanics
    without owning HTTP policy.
    """
    archive = ZipFile(BytesIO(package_bytes))

    with archive:
        members = [
            member
            for member in archive.infolist()
            if not member.is_dir()
            and not PurePosixPath(member.filename).name.startswith(".")
            and "__MACOSX" not in PurePosixPath(member.filename).parts
        ]
        pdf_members = [
            member for member in members if PurePosixPath(member.filename).suffix.lower() == ".pdf"
        ]
        json_members = [
            member for member in members if PurePosixPath(member.filename).suffix.lower() == ".json"
        ]
        if not manifest_override and len(json_members) != 1:
            raise ValueError(
                "Mapped ZIP must contain exactly one JSON manifest file, or paste manifest JSON in the form"
            )
        manifest_text = manifest_override or read_member(archive, json_members[0]).decode("utf-8")
        manifest_payload = decode_manifest(manifest_text)
        pdf_member = select_pdf(pdf_members, manifest_payload)
        pdf_bytes = read_member(archive, pdf_member)
        if not pdf_bytes:
            raise ValueError("Mapped ZIP PDF file is empty")
        return MappedZipContent(
            manifest_text=manifest_text,
            original_filename=PurePosixPath(pdf_member.filename).name,
            pdf_bytes=pdf_bytes,
        )
