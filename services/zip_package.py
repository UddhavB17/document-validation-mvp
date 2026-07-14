"""Safe ZIP intake and normalization for unordered loan-document packages."""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
import shutil
import stat
from typing import Any
from zipfile import BadZipFile, ZipFile, ZipInfo

import fitz
from openpyxl import load_workbook

from services.config import get_int


ALLOWED_PACKAGE_EXTENSIONS = frozenset({".pdf", ".png", ".jpg", ".jpeg", ".xlsx"})
MACOS_METADATA_NAMES = frozenset({".DS_Store"})


class PackageValidationError(ValueError):
    """Raised when an archive cannot be handled safely and deterministically."""


def max_package_files() -> int:
    return get_int("MAX_ZIP_FILES", 200, minimum=1, maximum=2000)


def max_package_pages() -> int:
    return get_int("MAX_ZIP_PAGES", 1000, minimum=1, maximum=5000)


def max_extracted_bytes() -> int:
    megabytes = get_int("MAX_ZIP_EXTRACTED_SIZE_MB", 500, minimum=1, maximum=2000)
    return megabytes * 1024 * 1024


def max_xlsx_rows() -> int:
    return get_int("MAX_XLSX_ROWS_PER_SHEET", 10000, minimum=1, maximum=100000)


def max_xlsx_columns() -> int:
    return get_int("MAX_XLSX_COLUMNS_PER_SHEET", 50, minimum=1, maximum=500)


def normalize_zip_package(zip_path: str | Path, package_dir: str | Path) -> dict[str, Any]:
    """Validate a ZIP and normalize its PDFs, images and workbooks into one PDF.

    Archive order is preserved, while every member receives a generated storage
    name and a stable ``source_document_id``. No archive-controlled path is ever
    used as a filesystem destination.
    """
    zip_path = Path(zip_path)
    package_dir = Path(package_dir)
    source_dir = package_dir / "sources"
    source_dir.mkdir(parents=True, exist_ok=True)
    normalized_pdf = package_dir / "normalized.pdf"

    output = fitz.open()
    inventory: list[dict[str, Any]] = []
    try:
        with ZipFile(zip_path) as archive:
            members = _validated_members(archive)
            for sequence, info in enumerate(members, start=1):
                suffix = Path(info.filename).suffix.lower()
                source_document_id = f"file-{sequence:04d}"
                stored_path = source_dir / f"{source_document_id}{suffix}"
                with archive.open(info, "r") as source, stored_path.open("wb") as destination:
                    shutil.copyfileobj(source, destination, length=1024 * 1024)

                first_page = output.page_count + 1
                page_count, source_metadata = _append_source(output, stored_path, suffix)
                last_page = output.page_count
                if output.page_count > max_package_pages():
                    raise PackageValidationError(
                        f"ZIP contains more than {max_package_pages()} normalized pages"
                    )
                inventory.append(
                    {
                        "source_document_id": source_document_id,
                        "original_filename": info.filename,
                        "file_type": suffix.removeprefix("."),
                        "source_size_bytes": info.file_size,
                        "page_count": page_count,
                        "internal_page_start": first_page,
                        "internal_page_end": last_page,
                        "pages": list(range(first_page, last_page + 1)),
                        **source_metadata,
                    }
                )

        if output.page_count == 0:
            raise PackageValidationError("ZIP contains no supported document pages")
        output.save(normalized_pdf, garbage=4, deflate=True)
    except BadZipFile as exc:
        raise PackageValidationError("File is not a valid ZIP archive") from exc
    except Exception:
        normalized_pdf.unlink(missing_ok=True)
        raise
    finally:
        output.close()

    result = {
        "normalized_pdf_path": str(normalized_pdf),
        "total_files": len(inventory),
        "total_pages": sum(int(item["page_count"]) for item in inventory),
        "documents": inventory,
    }
    (package_dir / "package.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    return result


def load_package_metadata(package_dir: str | Path) -> dict[str, Any]:
    metadata_path = Path(package_dir) / "package.json"
    if not metadata_path.is_file():
        raise FileNotFoundError("Prepared ZIP package was not found")
    return json.loads(metadata_path.read_text(encoding="utf-8"))


def _validated_members(archive: ZipFile) -> list[ZipInfo]:
    accepted: list[ZipInfo] = []
    unsupported: list[str] = []
    total_size = 0
    for info in archive.infolist():
        if info.is_dir() or _is_macos_metadata(info.filename):
            continue
        _validate_member_path(info)
        if info.flag_bits & 0x1:
            raise PackageValidationError(f"Encrypted ZIP member is not supported: {info.filename}")
        if _is_symlink(info):
            raise PackageValidationError(f"Symbolic links are not allowed in ZIP files: {info.filename}")

        suffix = Path(info.filename).suffix.lower()
        if suffix == ".zip":
            raise PackageValidationError(f"Nested ZIP files are not allowed: {info.filename}")
        if suffix not in ALLOWED_PACKAGE_EXTENSIONS:
            unsupported.append(info.filename)
            continue

        total_size += int(info.file_size)
        if total_size > max_extracted_bytes():
            raise PackageValidationError(
                f"Expanded ZIP is too large; maximum is {max_extracted_bytes() // (1024 * 1024)}MB"
            )
        if info.file_size and (not info.compress_size or info.file_size / info.compress_size > 200):
            raise PackageValidationError(f"Suspicious compression ratio in ZIP member: {info.filename}")
        accepted.append(info)

    if unsupported:
        names = ", ".join(unsupported[:5])
        extra = "" if len(unsupported) <= 5 else f" and {len(unsupported) - 5} more"
        raise PackageValidationError(
            f"Unsupported files in ZIP ({names}{extra}); only PDF, PNG, JPG, JPEG and XLSX are accepted"
        )
    if not accepted:
        raise PackageValidationError("ZIP contains no PDF or image documents")
    if len(accepted) > max_package_files():
        raise PackageValidationError(f"ZIP contains more than {max_package_files()} files")
    return accepted


def _validate_member_path(info: ZipInfo) -> None:
    raw_name = info.filename.replace("\\", "/")
    if not raw_name or "\x00" in raw_name:
        raise PackageValidationError("ZIP contains an invalid member name")
    path = PurePosixPath(raw_name)
    if path.is_absolute() or ".." in path.parts or (path.parts and ":" in path.parts[0]):
        raise PackageValidationError(f"Unsafe path in ZIP archive: {info.filename}")


def _is_macos_metadata(filename: str) -> bool:
    path = PurePosixPath(filename.replace("\\", "/"))
    return "__MACOSX" in path.parts or path.name in MACOS_METADATA_NAMES or path.name.startswith("._")


def _is_symlink(info: ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0xFFFF
    return stat.S_ISLNK(mode)


def _append_source(
    output: fitz.Document,
    source_path: Path,
    suffix: str,
) -> tuple[int, dict[str, Any]]:
    try:
        if suffix == ".pdf":
            source = fitz.open(source_path)
            try:
                if getattr(source, "needs_pass", False):
                    raise PackageValidationError(
                        f"Password-protected PDF is not supported: {source_path.name}"
                    )
                if source.page_count == 0:
                    raise PackageValidationError(f"PDF has no pages: {source_path.name}")
                output.insert_pdf(source)
                return source.page_count, {}
            finally:
                source.close()

        if suffix == ".xlsx":
            return _append_xlsx(output, source_path)

        image = fitz.open(source_path)
        try:
            image_pdf_bytes = image.convert_to_pdf()
        finally:
            image.close()
        image_pdf = fitz.open("pdf", image_pdf_bytes)
        try:
            output.insert_pdf(image_pdf)
            return image_pdf.page_count, {}
        finally:
            image_pdf.close()
    except PackageValidationError:
        raise
    except Exception as exc:
        raise PackageValidationError(f"Unreadable document in ZIP: {source_path.name}") from exc


def _append_xlsx(
    output: fitz.Document,
    source_path: Path,
) -> tuple[int, dict[str, Any]]:
    """Render non-empty workbook cells to deterministic landscape PDF pages."""
    _validate_xlsx_container(source_path)
    try:
        workbook = load_workbook(
            source_path,
            read_only=False,
            data_only=False,
            keep_links=False,
        )
    except Exception as exc:
        raise PackageValidationError(f"Unreadable XLSX workbook: {source_path.name}") from exc

    initial_pages = output.page_count
    rendered_sheets: list[str] = []
    try:
        for worksheet in workbook.worksheets:
            rows, actual_row_count, actual_column_count = _worksheet_value_table(worksheet)
            if actual_row_count > max_xlsx_rows():
                raise PackageValidationError(
                    f"XLSX sheet {worksheet.title!r} contains more than "
                    f"{max_xlsx_rows()} non-empty rows"
                )
            if actual_column_count > max_xlsx_columns():
                raise PackageValidationError(
                    f"XLSX sheet {worksheet.title!r} contains more than "
                    f"{max_xlsx_columns()} non-empty columns"
                )
            if not rows:
                continue
            rendered_sheets.append(worksheet.title)
            _render_worksheet_pages(output, source_path.name, worksheet.title, rows)
    finally:
        workbook.close()

    page_count = output.page_count - initial_pages
    if page_count == 0:
        raise PackageValidationError(f"XLSX workbook contains no non-empty worksheets: {source_path.name}")
    return page_count, {"worksheets": rendered_sheets}


def _validate_xlsx_container(source_path: Path) -> None:
    """Bound the second compression layer inside the XLSX container."""
    try:
        with ZipFile(source_path) as workbook_zip:
            expanded_size = 0
            for info in workbook_zip.infolist():
                if info.is_dir():
                    continue
                expanded_size += int(info.file_size)
                if expanded_size > max_extracted_bytes():
                    raise PackageValidationError(
                        f"Expanded XLSX is too large: {source_path.name}"
                    )
                if info.file_size and (
                    not info.compress_size or info.file_size / info.compress_size > 200
                ):
                    raise PackageValidationError(
                        f"Suspicious compression ratio in XLSX workbook: {source_path.name}"
                    )
    except BadZipFile as exc:
        raise PackageValidationError(f"Unreadable XLSX workbook: {source_path.name}") from exc


def _cell_text(value: Any) -> str:
    if value is None:
        return ""
    text = " ".join(str(value).replace("\x00", " ").split())
    return text[:120]


def _worksheet_value_table(worksheet: Any) -> tuple[list[list[str]], int, int]:
    """Return a compact table based on value-bearing cells, not Excel formatting bounds."""
    values: dict[tuple[int, int], str] = {}
    for cell in worksheet._cells.values():
        text = _cell_text(getattr(cell, "value", None))
        if text:
            values[(int(cell.row), int(cell.column))] = text
    if not values:
        return [], 0, 0

    source_rows = sorted({row for row, _column in values})
    source_columns = sorted({column for _row, column in values})
    table = [
        [values.get((row, column), "") for column in source_columns]
        for row in source_rows
    ]
    return table, len(source_rows), len(source_columns)


def _render_worksheet_pages(
    output: fitz.Document,
    workbook_name: str,
    worksheet_name: str,
    rows: list[list[str]],
) -> None:
    page_width, page_height = 842.0, 595.0
    margin = 30.0
    title_height = 28.0
    row_height = 15.0
    rows_per_page = int((page_height - (2 * margin) - title_height) // row_height)
    columns_per_page = 8
    column_count = max(len(row) for row in rows)

    for column_start in range(0, column_count, columns_per_page):
        column_end = min(column_start + columns_per_page, column_count)
        for row_start in range(0, len(rows), rows_per_page):
            row_end = min(row_start + rows_per_page, len(rows))
            page = output.new_page(width=page_width, height=page_height)
            page.insert_text(
                (margin, margin - 8),
                (
                    f"Workbook: {workbook_name} | Sheet: {worksheet_name} | "
                    f"Columns {column_start + 1}-{column_end} | Rows {row_start + 1}-{row_end}"
                ),
                fontsize=8,
            )
            table_top = margin + title_height
            cell_width = (page_width - (2 * margin)) / (column_end - column_start)
            for visible_row, row_index in enumerate(range(row_start, row_end)):
                y = table_top + (visible_row * row_height)
                row = rows[row_index]
                for visible_column, column_index in enumerate(range(column_start, column_end)):
                    x = margin + (visible_column * cell_width)
                    page.draw_rect(
                        fitz.Rect(x, y, x + cell_width, y + row_height),
                        color=(0.72, 0.72, 0.72),
                        width=0.35,
                    )
                    value = row[column_index] if column_index < len(row) else ""
                    page.insert_textbox(
                        fitz.Rect(x + 2, y + 2, x + cell_width - 2, y + row_height - 1),
                        value[:28],
                        fontsize=6.5,
                        fontname="helv",
                        lineheight=1.0,
                    )
