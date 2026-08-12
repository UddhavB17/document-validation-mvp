import pytest

from services.trusted_candidate_resolver import resolve_trusted_candidate
from services.validation_gates import attach_field_provenance


@pytest.mark.parametrize(
    ("field", "expected", "text", "observed"),
    [
        (
            "date_of_birth",
            "28-November-1994",
            "Date of Birth\nBlood Group\nUnknown\n28/11/1994",
            "28/11/1994",
        ),
        (
            "pan_number",
            "ABCDE1234F",
            "Permanent Account Number\nABCDE 1234 F",
            "ABCDE 1234 F",
        ),
        (
            "aadhaar_number",
            "123456789012",
            "Aadhaar Number\n1234 5678 9012",
            "1234 5678 9012",
        ),
        (
            "phone_number",
            "9876543210",
            "Mobile Number\n+91 9876543210",
            "+91 9876543210",
        ),
        (
            "pin_code",
            "110001",
            "Postal Code\n110001",
            "110001",
        ),
    ],
)
def test_resolver_returns_observed_labeled_identifier(
    field: str,
    expected: str,
    text: str,
    observed: str,
) -> None:
    candidate = resolve_trusted_candidate(field, expected, text)

    assert candidate is not None
    assert candidate["observed_value"] == observed
    assert candidate["match_method"] == "normalized_exact"


def test_resolver_rejects_relative_name_as_applicant_name() -> None:
    assert resolve_trusted_candidate(
        "applicant_name",
        "Ramesh Kumar",
        "Father Name\nRAMESH KUMAR",
    ) is None


def test_resolver_rejects_property_address_as_person_address() -> None:
    assert resolve_trusted_candidate(
        "address",
        "12 Market Road Delhi 110001",
        "Property Address\n12 Market Road\nDelhi 110001",
    ) is None


def test_recovery_provenance_survives_standard_provenance_refresh() -> None:
    page = {
        "page_number": 67,
        "ocr_confidence": 0.93,
        "classification_confidence": 1.0,
        "document_type": "Driving License",
        "detection_method": "detected",
        "extracted_fields": {
            "dob": "28/11/1994",
            "_trusted_candidate_recovery": {
                "date_of_birth": {
                    "confidence": 0.93,
                    "anchor": "date_of_birth_label",
                    "match_method": "normalized_exact",
                    "ocr_line": 8,
                }
            },
        },
    }

    attach_field_provenance(page)

    provenance = page["extracted_fields"]["_field_provenance"]["dob"]
    assert provenance["resolution_method"] == "trusted_candidate_match"
    assert provenance["anchor_evidence"] == [
        "date_of_birth_label",
        "trusted_value_present_in_ocr",
    ]
    assert provenance["field_confidence"] == 0.93
