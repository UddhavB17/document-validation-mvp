import pytest
from services.normalization import normalize_date, ExtractedField, normalize_extracted_fields
from services.field_verification import verify_date

def test_pydantic_model_extracted_field() -> None:
    # Test valid ExtractedField creation
    field = ExtractedField(
        field_name="date_of_birth",
        raw_value="03/04/25",
        normalized_value="2025-04-03",
        field_type="date",
        confidence=1.0,
        normalization_status="success"
    )
    assert field.field_name == "date_of_birth"
    assert field.raw_value == "03/04/25"
    assert field.normalized_value == "2025-04-03"
    assert field.field_type == "date"
    assert field.normalization_status == "success"


def test_date_normalization_two_digit_years() -> None:
    # Two-digit year: "03/04/25" -> "2025-04-03"
    val, status = normalize_date("03/04/25")
    assert status == "success"
    assert val == "2025-04-03"
    
    # Older two-digit year: "03/04/65" -> "1965-04-03" (Pivot logic)
    val, status = normalize_date("03/04/65")
    assert status == "success"
    assert val == "1965-04-03"


def test_date_normalization_ambiguous_cases() -> None:
    # Ambiguous DMY vs MDY: "03/04/2025" must resolve to 3 April, not 4 March
    val, status = normalize_date("03/04/2025")
    assert status == "success"
    assert val == "2025-04-03"

    # Another ambiguous case: "07/11/2025" -> 7 November, not 11 July
    val, status = normalize_date("07/11/2025")
    assert status == "success"
    assert val == "2025-11-07"


def test_date_normalization_10_real_world_variants() -> None:
    variants = [
        ("19 Sept 2025", "2025-09-19"),
        ("19/09/2025", "2025-09-19"),
        ("19-09-25", "2025-09-19"),
        ("19.09.2025", "2025-09-19"),
        ("Sept 19, 2025", "2025-09-19"),
        ("19-Sep-25", "2025-09-19"),
        ("19 Sep 25", "2025-09-19"),
        ("19.Sep.2025", "2025-09-19"),
        ("September 19, 2025", "2025-09-19"),
        ("2025-09-19", "2025-09-19"),
        ("19/09/25", "2025-09-19"),
    ]
    for raw, expected in variants:
        val, status = normalize_date(raw)
        assert status == "success", f"Failed parsing: {raw}"
        assert val == expected, f"Expected {expected} for {raw}, got {val}"


def test_invalid_date_normalization_fails_gracefully() -> None:
    val, status = normalize_date("invalid-date-string")
    assert status == "failed"
    assert val is None

    val, status = normalize_date("")
    assert status == "failed"
    assert val is None


def test_normalize_extracted_fields_triggers_llm_fallback() -> None:
    # Success case
    extracted = {"date_of_birth": "03/04/25", "applicant_name": "Ramesh Kumar"}
    normed = normalize_extracted_fields(extracted)
    assert normed["date_of_birth"] == "2025-04-03"
    assert "_llm_field_extraction" not in normed
    assert "_date_of_birth_metadata" in normed
    
    # Failed case
    extracted_fail = {"date_of_birth": "not-a-date", "applicant_name": "Ramesh Kumar"}
    normed_fail = normalize_extracted_fields(extracted_fail)
    assert normed_fail["date_of_birth"] is None
    assert normed_fail["_llm_field_extraction"]["status"] == "fields_extracted"
    assert normed_fail["_llm_field_extraction"]["reason"] == "date_normalization_failed_date_of_birth"
    assert normed_fail["_date_of_birth_metadata"]["normalization_status"] == "failed"


def test_verify_date_routes_failed_normalization_to_llm_fallback() -> None:
    # Verify exact match
    res = verify_date("03/04/25", "03/04/2025")
    assert res.match is True
    assert res.confidence == 1.0
    
    # Verify failed normalization falls back to LLM (confidence = 0.0)
    res_fail = verify_date("not-a-date", "03/04/2025")
    assert res_fail.match is False
    assert res_fail.confidence == 0.0
    assert res_fail.mismatch_reason == "Date could not be normalized"
