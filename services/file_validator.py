"""File validation for uploaded loan-file PDFs."""

from pathlib import Path


def validate_upload(filename: str) -> dict[str, object]:
    suffix = Path(filename).suffix.lower()
    errors: list[str] = []

    if suffix != ".pdf":
        errors.append("Only PDF uploads are supported.")

    return {"is_valid": not errors, "errors": errors}
