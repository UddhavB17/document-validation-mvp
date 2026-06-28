"""File-level validation for uploaded loan-file PDFs."""

from pathlib import Path

MAX_FILE_SIZE_BYTES = 100 * 1024 * 1024
ALLOWED_EXTENSIONS: frozenset[str] = frozenset({".pdf"})


def validate_file(file_path: str | Path, file_size_bytes: int) -> dict[str, object]:
    """Validate a saved PDF and count digital versus scanned pages."""
    path = Path(file_path)

    if path.suffix.lower() != ".pdf":
        return {"valid": False, "error": "Only PDF files accepted"}

    if file_size_bytes == 0:
        return {"valid": False, "error": "File is empty"}

    if file_size_bytes > MAX_FILE_SIZE_BYTES:
        return {"valid": False, "error": "File too large, max 100MB"}

    try:
        import fitz

        doc = fitz.open(path)
        if getattr(doc, "needs_pass", False):
            doc.close()
            return {"valid": False, "error": "File is password protected"}
    except Exception as exc:
        message = str(exc).lower()
        if "password" in message:
            return {"valid": False, "error": "File is password protected"}
        return {"valid": False, "error": "File is corrupted or unreadable"}

    try:
        total_pages = doc.page_count
        if total_pages == 0:
            return {"valid": False, "error": "PDF has no pages"}

        digital_pages = 0
        scanned_pages = 0
        for page in doc:
            text = page.get_text().strip()
            if len(text) > 50:
                digital_pages += 1
            else:
                scanned_pages += 1

        return {
            "valid": True,
            "total_pages": total_pages,
            "digital_pages": digital_pages,
            "scanned_pages": scanned_pages,
            "message": "File validated successfully",
        }
    finally:
        doc.close()


def validate_upload(filename: str, file_size_bytes: int = 0) -> dict[str, object]:
    """Lightweight upload filename and size validation."""
    errors: list[str] = []
    suffix = Path(filename).suffix.lower()

    if not filename or filename.strip() == "":
        errors.append("Filename must not be empty.")
    elif suffix not in ALLOWED_EXTENSIONS:
        errors.append(f"Only PDF files accepted")

    if file_size_bytes > MAX_FILE_SIZE_BYTES:
        errors.append("File too large, max 100MB")

    return {"is_valid": not errors, "errors": errors}
