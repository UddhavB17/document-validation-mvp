"""A shared area and PIN must not mask different locality codes."""

import pytest

from services.consistency_checks import run_consistency_checks
from services.identity_matching import address_component_conflict

PERMANENT = "Ward 01, 42b, 46b, Naya Gaon, Shivapur, Haryana, 125001"
AADHAAR = "W/O: Sample Person, VPO 42 B Naya Gaon, 43 B, Shivapur, Haryana, 125001"


def test_standalone_locality_disagrees_within_same_numbered_area():
    assert address_component_conflict(PERMANENT, AADHAAR) == "locality identifier"
    assert address_component_conflict(PERMANENT, AADHAAR.replace("43 B", "46 B")) is None
    assert address_component_conflict(PERMANENT, AADHAAR.replace("125001", "125002")) is None


@pytest.mark.parametrize(
    ("alternate", "aadhaar_last4", "should_flag"),
    [
        ("VPO 42 B Naya Gaon, Shivapur, Haryana, 125001", "1234", True),
        ("VPO 42 B Naya Gaon, 43b, Shivapur, Haryana, 125001", "1234", False),
        ("VPO 42 B Naya Gaon, Shivapur, Haryana, 125001", "4321", False),
    ],
)
def test_aadhaar_reports_permanent_locality_when_matching_alternate_omits_it(
    alternate, aadhaar_last4, should_flag
):
    people = {
        "primary": {"applicant_name": "Arun Verma"},
        "coapplicant_1": {
            "applicant_name": "Meera Verma",
            "aadhaar_last4": "1234",
            "address_subtype": "Permanent",
            "address": PERMANENT,
            "communication_address": alternate,
        },
    }
    result = run_consistency_checks(
        [{
            "page_number": 8,
            "document_type": "Aadhaar",
            "page_type": "digital",
            "classification_confidence": 0.99,
            "ocr_text": f"DigiLocker verified e-Aadhaar\nMasked Aadhaar number: XXXXXXXX{aadhaar_last4}\n"
            f"Name: Meera Verma\nAddress: {AADHAAR}",
            "extracted_fields": {
                "applicant_name": "Meera Verma",
                "aadhaar_last4": aadhaar_last4,
                "address": AADHAAR,
            },
        }],
        {"people": people},
    )
    conflicts = [row for row in result if row["rule_id"] == "TRUSTED_ADDRESS_MISMATCH"]
    assert len(conflicts) == int(should_flag)
    if should_flag:
        (finding,) = conflicts
        assert finding["page_number"] == 8
        assert finding["expected_value"] == PERMANENT
        assert finding["found_value"] == AADHAAR
