from services.file_validator import validate_upload


def test_validate_upload_accepts_pdf() -> None:
    result = validate_upload("loan-file.pdf")
    assert result["is_valid"] is True


def test_validate_upload_rejects_non_pdf() -> None:
    result = validate_upload("loan-file.docx")
    assert result["is_valid"] is False
