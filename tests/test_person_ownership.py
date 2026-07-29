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
        "pan_number": "BCXPL9010K",
        "date_of_birth": "18-May-1994",
        "phone_number": "8107058694",
    },
    "coapplicant_1": {
        "role": "coapplicant",
        "applicant_name": "Unkar Lal",
        "pan_number": "BBEPL4329P",
        "date_of_birth": "05-June-1961",
        "phone_number": "9509341692",
    },
    "coapplicant_2": {
        "role": "coapplicant",
        "applicant_name": "Radha Bai",
        "pan_number": "JGZPB3257C",
        "date_of_birth": "01-January-1962",
        "phone_number": "7339781668",
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
                "pan_number": "BBEPL4329P",
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
                "pan_number": "BCXPL9010K",
                "dob": "1994-05-18",
            },
        },
        {
            "page_number": 10,
            "document_type": "PAN",
            "extracted_fields": {
                "applicant_name": "UNKAR LAL",
                "pan_number": "BBEPL4329P",
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
                "pan_number": "BCXPL9010K",
                "dob": "1994-05-18",
            },
        },
        {
            "page_number": 10,
            "document_type": "PAN",
            "extracted_fields": {
                "applicant_name": "UNKAR LAL",
                "pan_number": "BBEPL4329P",
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


def test_strong_pan_overrides_wrong_provided_mapping() -> None:
    owner = resolve_person_owner(
        {
            "document_type": "PAN",
            "extracted_fields": {
                "applicant_name": "UNKAR LAL",
                "pan_number": "BBEPL4329P",
            },
        },
        PEERU_FAMILY,
        "PAN",
        provided_person_id="primary",
    )
    assert owner["person_id"] == "coapplicant_1"
    assert "overrode_provided_mapping" in owner["evidence"]
