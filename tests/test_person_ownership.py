"""Person ownership must stop cross-person TRUSTED_* mismatches."""

from __future__ import annotations

from services.consistency_checks import run_consistency_checks
from services.person_ownership import (
    assign_page_owners,
    resolve_person_owner,
)


PEERU_FAMILY = {
    "primary": {
        "role": "primary",
        "applicant_name": "Peeru Lal",
        "pan_number": "TSTAA0001T",
        "date_of_birth": "18-May-1994",
        "phone_number": "9000000001",
    },
    "coapplicant_1": {
        "role": "coapplicant",
        "applicant_name": "Unkar Lal",
        "pan_number": "TSTBB0002T",
        "date_of_birth": "05-June-1961",
        "phone_number": "9000000002",
    },
    "coapplicant_2": {
        "role": "coapplicant",
        "applicant_name": "Radha Bai",
        "pan_number": "TSTCC0003T",
        "date_of_birth": "01-January-1962",
        "phone_number": "9000000003",
    },
}


def test_bank_statement_owner_resolves_from_ocr_name() -> None:
    pages = [
        {
            "page_number": 1,
            "document_type": "Bank Statement",
            "ocr_text": "OF Mr. PEERU LAL AT 10521 DAU,RURAL BANKING END BALANCE 1618.80 Cr",
            "extracted_fields": {},
        }
    ]
    assign_page_owners(pages, {"people": PEERU_FAMILY})
    assert pages[0]["person_id"] == "primary"


def test_passbook_owner_resolves_from_ocr_name() -> None:
    pages = [
        {
            "page_number": 1,
            "document_type": "Passbook",
            "ocr_text": "Punjab National Bank Passbook Account Holder PEERU LAL SEMLI BAKHTA",
            "extracted_fields": {},
        }
    ]
    assign_page_owners(pages, {"people": PEERU_FAMILY})
    assert pages[0]["person_id"] == "primary"

    owner = resolve_person_owner(
        {
            "document_type": "PAN",
            "extracted_fields": {
                "applicant_name": "UNKAR LAL",
                "pan_number": "TSTBB0002T",
                "dob": "1961-06-05",
            },
        },
        PEERU_FAMILY,
        "PAN",
    )
    assert owner["person_id"] == "coapplicant_1"
    assert owner["confidence"] >= 0.7


def test_radha_cibil_resolves_to_coapplicant_2() -> None:
    owner = resolve_person_owner(
        {
            "document_type": "CIBIL Report",
            "extracted_fields": {"applicant_name": "RADHA BAI"},
        },
        PEERU_FAMILY,
        "CIBIL Report",
    )
    assert owner["person_id"] == "coapplicant_2"


def test_cibil_does_not_default_to_primary_when_unmatched() -> None:
    owner = resolve_person_owner(
        {
            "document_type": "CIBIL Report",
            "extracted_fields": {"applicant_name": "Somebody Else Entirely"},
        },
        PEERU_FAMILY,
        "CIBIL Report",
    )
    assert owner["person_id"] is None


def test_assign_page_owners_stamps_coapplicant_pages() -> None:
    pages = [
        {
            "page_number": 7,
            "document_type": "PAN",
            "extracted_fields": {
                "applicant_name": "PEERU LAL",
                "pan_number": "TSTAA0001T",
                "dob": "1994-05-18",
            },
        },
        {
            "page_number": 10,
            "document_type": "PAN",
            "extracted_fields": {
                "applicant_name": "UNKAR LAL",
                "pan_number": "TSTBB0002T",
                "dob": "1961-06-05",
            },
        },
        {
            "page_number": 15,
            "document_type": "CIBIL Report",
            "extracted_fields": {"applicant_name": "RADHA BAI"},
        },
    ]
    assign_page_owners(pages, {"people": PEERU_FAMILY})
    assert pages[0]["person_id"] == "primary"
    assert pages[1]["person_id"] == "coapplicant_1"
    assert pages[2]["person_id"] == "coapplicant_2"


def test_no_cross_person_trusted_mismatches_for_peeru_family() -> None:
    pages = [
        {
            "page_number": 7,
            "document_type": "PAN",
            "extracted_fields": {
                "applicant_name": "PEERU LAL",
                "pan_number": "TSTAA0001T",
                "dob": "1994-05-18",
            },
        },
        {
            "page_number": 10,
            "document_type": "PAN",
            "extracted_fields": {
                "applicant_name": "UNKAR LAL",
                "pan_number": "TSTBB0002T",
                "dob": "05-June-1961",
            },
        },
        {
            "page_number": 15,
            "document_type": "CIBIL Report",
            # Intentionally missing person_id — ownership must infer Radha.
            "extracted_fields": {"applicant_name": "RADHA BAI"},
        },
        {
            "page_number": 18,
            "document_type": "CIBIL Report",
            "person_id": "primary",  # Wrong stamp; identity must override.
            "extracted_fields": {"applicant_name": "UNKAR LAL"},
        },
    ]
    anomalies = run_consistency_checks(pages, {"people": PEERU_FAMILY})
    trusted = [
        item
        for item in anomalies
        if item["rule_id"].startswith("TRUSTED_")
        and "MISMATCH" in item["rule_id"]
    ]
    assert trusted == [], [item["rule_id"] for item in trusted]


SINGLE_PERSON = {
    "primary": {
        "role": "primary",
        "applicant_name": "Suthar Anupkumar",
        "pan_number": "TSTAA0001T",
        "father_name": "Chetanbhai Mohanlal Suthar",
    }
}


def test_single_person_fallback_refused_when_observed_name_contradicts() -> None:
    # A guarantor's Aadhaar in a single-person manifest must stay unassigned
    # instead of defaulting to the primary and producing false mismatches.
    owner = resolve_person_owner(
        [
            {
                "document_type": "Aadhaar",
                "extracted_fields": {
                    "applicant_name": "Solanki Jayesh Chamanbhai",
                    "aadhaar_number": "991010972822",
                },
                "ocr_text": "",
            }
        ],
        SINGLE_PERSON,
        "Aadhaar",
    )
    assert owner["person_id"] is None
    assert "observed_name_contradicts_manifest" in owner["evidence"]


def test_single_person_fallback_kept_for_matching_or_absent_names() -> None:
    own_doc = resolve_person_owner(
        [
            {
                "document_type": "Aadhaar",
                "extracted_fields": {"applicant_name": "Suthar Anupkumar"},
                "ocr_text": "",
            }
        ],
        SINGLE_PERSON,
        "Aadhaar",
    )
    assert own_doc["person_id"] == "primary"

    nameless = resolve_person_owner(
        [{"document_type": "Aadhaar", "extracted_fields": {}, "ocr_text": ""}],
        SINGLE_PERSON,
        "Aadhaar",
    )
    assert nameless["person_id"] == "primary"


def test_name_with_trusted_father_token_matches_same_person() -> None:
    from services.person_ownership import name_matches_trusted_person

    # "Anupkumar Chetanbhai Suthar" = given name + father's name + surname:
    # the same person under Gujarati naming conventions.
    assert name_matches_trusted_person(
        "Anupkumar Chetanbhai Suthar", SINGLE_PERSON["primary"]
    )
    # A relative sharing the father/surname tokens is still a different person.
    assert not name_matches_trusted_person(
        "Aaratiben Anupkumar Suthar", SINGLE_PERSON["primary"]
    )


def test_duplicated_trusted_name_tokens_still_match() -> None:
    from services.person_ownership import name_matches_trusted_person

    assert name_matches_trusted_person(
        "Kuldeep", {"applicant_name": "Kuldeep KULDEEP"}
    )


def test_strong_pan_overrides_wrong_provided_mapping() -> None:
    owner = resolve_person_owner(
        {
            "document_type": "PAN",
            "extracted_fields": {
                "applicant_name": "UNKAR LAL",
                "pan_number": "TSTBB0002T",
            },
        },
        PEERU_FAMILY,
        "PAN",
        provided_person_id="primary",
    )
    assert owner["person_id"] == "coapplicant_1"
    assert "overrode_provided_mapping" in owner["evidence"]
