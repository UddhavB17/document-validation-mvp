"""File-level validation for uploaded loan-file PDFs.

Scope (owned by this team):
  - Extension / MIME type check (PDF only)
  - File size guard
  - Filename sanity check

Out of scope:
  - PDF content extraction (handled by OCR partner)
  - Text parsing or document classification
"""

from pathlib import Path

# 50 MB – adjust as needed
MAX_FILE_SIZE_BYTES: int = 50 * 1024 * 1024

ALLOWED_EXTENSIONS: frozenset[str] = frozenset({".pdf"})


def validate_upload(filename: str, file_size_bytes: int = 0) -> dict[str, object]:
    """Validate a PDF upload at the file level.

    Args:
        filename:        Original filename from the upload.
        file_size_bytes: File size in bytes (0 means size check is skipped).

    Returns:
        {"is_valid": bool, "errors": list[str]}
    """
    errors: list[str] = []

    # Extension check
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        errors.append(
            f"Only PDF uploads are supported (received '{suffix or 'no extension'}')."
        )

    # Size check (only when size is provided)
    if file_size_bytes > MAX_FILE_SIZE_BYTES:
        errors.append(
            f"File exceeds the {MAX_FILE_SIZE_BYTES // (1024 * 1024)} MB limit "
            f"({file_size_bytes // (1024 * 1024)} MB received)."
        )

    # Filename sanity
    if not filename or filename.strip() == "":
        errors.append("Filename must not be empty.")

    return {"is_valid": not errors, "errors": errors}
