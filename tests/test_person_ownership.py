"""Person ownership must stop cross-person TRUSTED_* mismatches."""

from __future__ import annotations

from services.consistency_checks import run_consistency_checks
from services.field_extractor import extract_fields
from services.person_ownership import (
    assign_page_owners,
    name_matches_trusted_person,
    ownership_anomalies_for_unassigned,
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


def test_nameless_bank_statement_does_not_emit_ownership_warning() -> None:
    page = {
        "page_number": 1,
        "document_type": "Bank Statement",
        "ocr_text": "Account Number: 123456789012\nTransaction Date Narration Debit Credit Balance",
        "extracted_fields": {"account_number": "123456789012"},
    }

    assign_page_owners([page], {"people": PEERU_FAMILY})

    assert page["person_id"] == "unassigned"
    assert ownership_anomalies_for_unassigned([page]) == []


def test_document_index_owner_survives_noisy_bank_continuation_page() -> None:
    page = {
        "page_number": 34,
        "document_type": "Bank Statement",
        "person_id": "coapplicant_2",
        "applicant_role": "coapplicant_2",
        "ocr_text": "Transaction ledger\nOutside Person\nDebit 1000.00\nBalance 5000.00",
        "extracted_fields": {
            "account_holder_name": "Outside Person",
            "_ownership": {
                "person_id": "coapplicant_2",
                "document_scope": "single_person",
                "evidence": ["document_index"],
            },
        },
    }

    assign_page_owners([page], {"people": PEERU_FAMILY})
    assign_page_owners([page], {"people": PEERU_FAMILY})

    assert page["person_id"] == "coapplicant_2"
    assert "document_index" in page["extracted_fields"]["_ownership"]["evidence"]
    assert ownership_anomalies_for_unassigned([page]) == []


def test_unmatched_bank_holder_still_emits_ownership_warning() -> None:
    page = {
        "page_number": 1,
        "document_type": "Bank Statement",
        "ocr_text": "Account Holder Name: Outside Person\nAccount Number: 123456789012",
        "extracted_fields": {"account_holder_name": "Outside Person"},
    }

    assign_page_owners([page], {"people": PEERU_FAMILY})

    assert page["person_id"] == "unassigned"
    assert [item["rule_id"] for item in ownership_anomalies_for_unassigned([page])] == [
        "AUTO_OWNER_UNRESOLVED"
    ]


def test_bank_statement_holder_beats_related_primary_and_clears_anomaly() -> None:
    people = {
        "primary": {"role": "primary", "applicant_name": "Kala Singh"},
        "coapplicant_1": {"role": "coapplicant", "applicant_name": "Seeta Seeta"},
        "coapplicant_2": {"role": "coapplicant", "applicant_name": "Kuldeep Singh"},
    }
    page = {
        "page_number": 19,
        "document_type": "Bank Statement",
        "source_filename": "Case/Co-Applicant/BANK/statement.pdf",
        "ocr_text": (
            "Account Summary\nWelcome:\nMr. Kuldeep Singh\nMr. Kuldeep Singh\n"
            "Not Available\nS/O: Kala Singh, Ward No 11\n"
            "Date of Statement: 31-07-2026\nSTATEMENT OF ACCOUNT\n"
            "Balance\n01/01/2026\nWDL TFR\n"
        ),
        # Reproduce the historical extractor error. Raw header evidence must
        # recover the holder instead of trusting this transaction description.
        "extracted_fields": {"account_holder_name": "WDL TFR"},
    }

    assign_page_owners([page], {"people": people})

    assert page["person_id"] == "coapplicant_2"
    assert "applicant_name" in page["extracted_fields"]["_ownership"]["evidence"]
    assert ownership_anomalies_for_unassigned([page]) == []


def test_banking_holder_layouts_generalize_across_names_and_labels() -> None:
    people = {
        "primary": {"role": "primary", "applicant_name": "Rajesh Verma"},
        "coapplicant_1": {"role": "coapplicant", "applicant_name": "Asha Verma"},
        "coapplicant_2": {"role": "coapplicant", "applicant_name": "Nitin Rao"},
    }
    cases = (
        ("Account Summary\nWelcome:\nMrs. Asha Verma\nW/O: Rajesh Verma", "coapplicant_1"),
        ("Account Holder Name: Nitin Rao\nS/O: Rajesh Verma", "coapplicant_2"),
        ("STATEMENT OF ACCOUNT OF Mr. Nitin Rao AT CITY BRANCH", "coapplicant_2"),
    )

    for text, expected_person_id in cases:
        owner = resolve_person_owner(
            {
                "document_type": "Bank Statement",
                "ocr_text": text,
                "extracted_fields": {},
            },
            people,
            "Bank Statement",
            source_filename="Case/Co-Applicant/BANK/statement.pdf",
        )
        assert owner["person_id"] == expected_person_id


def test_relationship_name_alone_never_becomes_bank_statement_holder() -> None:
    owner = resolve_person_owner(
        {
            "document_type": "Bank Statement",
            "ocr_text": "Account Summary\nS/O: Kala Singh, Ward No 11\nBalance",
            "extracted_fields": {},
        },
        {
            "primary": {"role": "primary", "applicant_name": "Kala Singh"},
            "coapplicant_1": {"role": "coapplicant", "applicant_name": "Seeta Singh"},
            "coapplicant_2": {"role": "coapplicant", "applicant_name": "Nitin Singh"},
        },
        "Bank Statement",
        source_filename="Case/Co-Applicant/BANK/statement.pdf",
    )

    assert owner["person_id"] is None
    assert "source_role_ambiguous" in owner["evidence"]


def test_equal_holder_evidence_never_defaults_to_primary() -> None:
    owner = resolve_person_owner(
        {
            "document_type": "Bank Statement",
            "ocr_text": "Account Holder Name: Kala Singh\nCustomer Name: Kuldeep Singh",
            "extracted_fields": {},
        },
        {
            "primary": {"role": "primary", "applicant_name": "Kala Singh"},
            "coapplicant_1": {"role": "coapplicant", "applicant_name": "Kuldeep Singh"},
        },
        "Bank Statement",
    )

    assert owner["person_id"] is None


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


def test_cheque_owner_resolves_from_exact_full_account_number() -> None:
    owner = resolve_person_owner(
        {
            "document_type": "Cheque",
            "ocr_text": "CHEQUE\nA/c No.\n41249946368",
            "extracted_fields": {"account_number": "41249946368"},
        },
        {
            "primary": {
                "applicant_name": "Kala Singh",
                "account_number": "41249946368",
            },
            "coapplicant_1": {
                "applicant_name": "Seeta Seeta",
                "account_number": "99999999999",
            },
        },
        "Cheque",
    )

    assert owner["person_id"] == "primary"
    assert owner["confidence"] == 1.0
    assert owner["evidence"] == ["account_number"]


def test_unique_full_account_number_overrides_wrong_source_role() -> None:
    owner = resolve_person_owner(
        {
            "document_type": "Passbook",
            "ocr_text": "PASSBOOK\nAccount No. 41249946368\nIFSC SBIN0031538",
            "extracted_fields": {"account_number": "41249946368"},
        },
        {
            "primary": {
                "applicant_name": "Kala Singh",
                "account_number": "41249946368",
            },
            "coapplicant_1": {
                "applicant_name": "Seeta Seeta",
                "account_number": "99999999999",
            },
        },
        "Passbook",
        source_filename="Co-Applicant/BANK/passbook.pdf",
    )

    assert owner["person_id"] == "primary"
    assert "account_number" in owner["evidence"]
    assert "overrode_source_role:coapplicant" in owner["evidence"]


def test_cheque_owner_resolves_from_printed_signature_holder_name() -> None:
    owner = resolve_person_owner(
        {
            "document_type": "Cheque",
            "ocr_text": (
                "State Bank Of India\nA/c No.\n41249946368\nMr. Kala Singh\nPlease sign above"
            ),
            # Reproduce the old extractor mistake from application 93.
            "extracted_fields": {"account_holder_name": "State Bank Of India"},
        },
        {
            "primary": {"applicant_name": "Kala Singh"},
            "coapplicant_1": {"applicant_name": "Seeta Seeta"},
        },
        "Cheque",
    )

    assert owner["person_id"] == "primary"
    assert owner["evidence"] == ["applicant_name"]


def test_cersai_debtor_pan_assigns_report_to_coapplicant_only() -> None:
    text = """Debtor Based Search Report
CERSAI Details
PAN
AAECC5770G
Search Criteria Entered
Name of the Debtor
RADHA BAI
PAN
TSTCC0003T
Search Output Details
Applicant PEERU LAL PAN TSTAA0001T
Co-Applicant UNKAR LAL PAN TSTBB0002T
"""
    owner = resolve_person_owner(
        {
            "document_type": "CERSAI Report",
            "ocr_text": text,
            "extracted_fields": extract_fields("CERSAI Report", text),
        },
        PEERU_FAMILY,
        "CERSAI Report",
    )

    assert owner["person_id"] == "coapplicant_2"
    assert owner["confidence"] == 1.0
    assert "cersai_debtor_pan_number" in owner["evidence"]


def test_cersai_primary_debtor_assigns_only_to_primary() -> None:
    text = """Debtor Based Search Report
Search Criteria Entered
Name of the Debtor
PEERU LAL
PAN
TSTAA0001T
Search Output Details
No Match Found
"""
    owner = resolve_person_owner(
        {
            "document_type": "CERSAI Report",
            "ocr_text": text,
            "extracted_fields": extract_fields("CERSAI Report", text),
        },
        PEERU_FAMILY,
        "CERSAI Report",
    )

    assert owner["person_id"] == "primary"
    assert owner["evidence"] == ["cersai_debtor_pan_number", "pan_number"]


def test_cersai_result_pages_inherit_debtor_owner_not_people_in_output() -> None:
    cover_text = """Debtor Based Search Report
Search Criteria Entered
Name of the Debtor
UNKAR LAL
PAN
TSTBB0002T
Search Output Details
"""
    pages = [
        {
            "page_number": 1,
            "document_type": "CERSAI Report",
            "ocr_text": cover_text,
            "extracted_fields": extract_fields("CERSAI Report", cover_text),
        },
        {
            "page_number": 2,
            "document_type": "CERSAI Report",
            "ocr_text": "Applicant PEERU LAL PAN TSTAA0001T; Co-Applicant RADHA BAI PAN TSTCC0003T",
            # Simulate stale/generic extraction from a result page. It must not
            # take ownership away from the debtor on the cover/search page.
            "extracted_fields": {
                "applicant_name": "PEERU LAL",
                "pan_number": "TSTAA0001T",
            },
        },
    ]

    assign_page_owners(pages, {"people": PEERU_FAMILY})

    assert [page["person_id"] for page in pages] == ["coapplicant_1", "coapplicant_1"]
    assert all(
        page["extracted_fields"]["_ownership"]["cersai_search_type"] == "debtor_based"
        for page in pages
    )


def test_unmatched_cersai_debtor_is_unassigned_instead_of_primary() -> None:
    text = """Debtor Based Search Report
Search Criteria Entered
Name of the Debtor
OUTSIDE PERSON
PAN
ZZZZZ9999Z
Search Output Details
No Match Found
"""
    page = {
        "page_number": 1,
        "document_type": "CERSAI Report",
        "ocr_text": text,
        "extracted_fields": extract_fields("CERSAI Report", text),
    }

    assign_page_owners([page], {"people": PEERU_FAMILY})

    assert page["person_id"] == "unassigned"
    anomalies = ownership_anomalies_for_unassigned([page])
    assert [item["rule_id"] for item in anomalies] == ["AUTO_OWNER_UNRESOLVED"]


def test_asset_based_cersai_remains_loan_level_and_ignores_result_pans() -> None:
    text = """Asset Based Search Report
CERSAI Details
PAN
AAECC5770G
Search Criteria Entered
Asset Category
Immovable
Search Output Details
Co-Applicant RADHA BAI PAN TSTCC0003T
"""
    page = {
        "document_type": "CERSAI Report",
        "ocr_text": text,
        "extracted_fields": extract_fields("CERSAI Report", text),
    }
    owner = resolve_person_owner(
        page,
        PEERU_FAMILY,
        "CERSAI Report",
    )

    assert owner["person_id"] is None
    assert owner["evidence"] == ["cersai_asset_based"]
    assert owner["document_scope"] == "loan_level"

    assign_page_owners([page], {"people": PEERU_FAMILY})

    assert page["person_id"] is None
    assert page["applicant_role"] is None
    assert page["extracted_fields"]["_ownership"] == {
        "person_id": None,
        "confidence": 1.0,
        "evidence": ["cersai_asset_based"],
        "source_role": None,
        "cersai_search_type": "asset_based",
        "document_scope": "loan_level",
    }
    assert ownership_anomalies_for_unassigned([page]) == []


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
        if item["rule_id"].startswith("TRUSTED_") and "MISMATCH" in item["rule_id"]
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
    assert name_matches_trusted_person("Anupkumar Chetanbhai Suthar", SINGLE_PERSON["primary"])
    # A relative sharing the father/surname tokens is still a different person.
    assert not name_matches_trusted_person("Aaratiben Anupkumar Suthar", SINGLE_PERSON["primary"])


def test_duplicated_trusted_name_tokens_still_match() -> None:
    from services.person_ownership import name_matches_trusted_person

    assert name_matches_trusted_person("Kuldeep", {"applicant_name": "Kuldeep KULDEEP"})


def test_passbook_owner_uses_duplicate_aware_name_matching() -> None:
    people = {
        "primary": {
            "role": "primary",
            "applicant_name": "Kala Singh",
        },
        "coapplicant_1": {
            "role": "coapplicant",
            "applicant_name": "Seeta Seeta",
        },
        "coapplicant_2": {
            "role": "coapplicant",
            "applicant_name": "Kuldeep Singh",
        },
    }

    owner = resolve_person_owner(
        {
            "document_type": "Passbook",
            "extracted_fields": {"account_holder_name": "'SEETA'"},
        },
        people,
        "Passbook",
        source_filename="Co-Applicant/BANK/passbook-front.jpg",
    )

    assert owner["person_id"] == "coapplicant_1"
    assert "applicant_name" in owner["evidence"]


def test_passbook_owner_uses_labeled_masked_aadhaar_last_four() -> None:
    people = {
        "primary": {
            "role": "primary",
            "applicant_name": "Kala Singh",
            "aadhaar_last4": "3436",
        },
        "coapplicant_1": {
            "role": "coapplicant",
            "applicant_name": "Seeta Seeta",
            "aadhaar_last4": "1641",
        },
        "coapplicant_2": {
            "role": "coapplicant",
            "applicant_name": "Kuldeep Singh",
            "aadhaar_last4": "8671",
        },
    }

    owner = resolve_person_owner(
        {
            "document_type": "Passbook",
            "ocr_text": "Punjab National Bank Passbook\nAadhaar XX1641",
            "extracted_fields": {},
        },
        people,
        "Passbook",
        source_filename="Co-Applicant/BANK/passbook-front.jpg",
    )

    assert owner["person_id"] == "coapplicant_1"
    assert "aadhaar_number" in owner["evidence"]


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


def test_clean_external_name_rejects_unsubstantiated_provided_mapping() -> None:
    owner = resolve_person_owner(
        {
            "document_type": "CIBIL Report",
            "extracted_fields": {"applicant_name": "EXTERNAL GUARANTOR"},
        },
        PEERU_FAMILY,
        "CIBIL Report",
        provided_person_id="primary",
    )
    assert owner["person_id"] is None
    assert owner["evidence"] == ["observed_name_contradicts_provided_mapping"]


def test_source_role_missing_from_trusted_never_defaults_to_primary() -> None:
    owner = resolve_person_owner(
        {
            "document_type": "PAN",
            "extracted_fields": {
                "applicant_name": "SUTHAR AARATIBEN ANUPKUMAR",
                "pan_number": "SXPPS4453F",
            },
        },
        SINGLE_PERSON,
        "PAN",
        source_filename="Co-Applicant/KYC/PAN.pdf",
    )
    assert owner["person_id"] is None
    assert owner["source_role"] == "coapplicant"
    assert "source_role_not_in_trusted_data" in owner["evidence"]
    assert "single_person_manifest" not in owner["evidence"]


def test_present_source_role_resolves_and_exact_identity_can_override_path() -> None:
    coapp = resolve_person_owner(
        {"document_type": "PAN", "extracted_fields": {}},
        {
            "primary": PEERU_FAMILY["primary"],
            "coapplicant_1": PEERU_FAMILY["coapplicant_1"],
        },
        "PAN",
        source_filename="Co_Applicant/KYC/PAN.pdf",
    )
    assert coapp["person_id"] == "coapplicant_1"

    misplaced_primary = resolve_person_owner(
        {
            "document_type": "PAN",
            "extracted_fields": {
                "applicant_name": "PEERU LAL",
                "pan_number": "TSTAA0001T",
            },
        },
        PEERU_FAMILY,
        "PAN",
        source_filename="Co-Applicant/KYC/misfiled.pdf",
    )
    assert misplaced_primary["person_id"] == "primary"
    assert "overrode_source_role:coapplicant" in misplaced_primary["evidence"]


def test_unlabeled_generic_and_raw_aadhaar_do_not_override_source_role() -> None:
    people = {
        "primary": {
            **PEERU_FAMILY["primary"],
            "aadhaar_number": "822113513365",
        },
        "coapplicant_1": PEERU_FAMILY["coapplicant_1"],
    }
    owner = resolve_person_owner(
        {
            "document_type": "Application Form",
            "ocr_text": "Bank Account Number 8221 1351 3365",
            "extracted_fields": {
                "_generic_evidence": {"aadhaar_numbers": ["822113513365"]},
            },
        },
        people,
        "Application Form",
        source_filename="Co-Applicant/Application/application.pdf",
    )

    assert owner["person_id"] == "coapplicant_1"
    assert owner["evidence"] == ["source_role:coapplicant"]


def test_phone_name_and_aadhaar_last4_cannot_override_source_role() -> None:
    people = {
        "primary": {
            **PEERU_FAMILY["primary"],
            "aadhaar_last4": "3365",
        },
        "coapplicant_1": PEERU_FAMILY["coapplicant_1"],
    }
    owner = resolve_person_owner(
        {
            "document_type": "Application Form",
            "extracted_fields": {
                "applicant_name": "PEERU LAL",
                "phone_number": "9000000001",
                "aadhaar_last4": "3365",
            },
        },
        people,
        "Application Form",
        source_filename="Co-Applicant/Application/application.pdf",
    )

    assert owner["person_id"] == "coapplicant_1"
    assert owner["evidence"] == ["source_role:coapplicant"]


def test_full_labeled_aadhaar_can_override_wrong_source_role() -> None:
    people = {
        "primary": {
            **PEERU_FAMILY["primary"],
            "aadhaar_number": "822113513365",
        },
        "coapplicant_1": PEERU_FAMILY["coapplicant_1"],
    }
    owner = resolve_person_owner(
        {
            "document_type": "Application Form",
            "ocr_text": "Aadhaar Number: 8221 1351 3365",
            "extracted_fields": {"aadhaar_number": "822113513365"},
        },
        people,
        "Application Form",
        source_filename="Co-Applicant/Application/misfiled.pdf",
    )

    assert owner["person_id"] == "primary"
    assert "overrode_source_role:coapplicant" in owner["evidence"]


def test_full_observed_aadhaar_does_not_override_when_trusted_has_last4_only() -> None:
    people = {
        "primary": {
            **PEERU_FAMILY["primary"],
            "aadhaar_last4": "3365",
        },
        "coapplicant_1": PEERU_FAMILY["coapplicant_1"],
    }
    owner = resolve_person_owner(
        {
            "document_type": "Application Form",
            "ocr_text": "Aadhaar Number: 8221 1351 3365",
            "extracted_fields": {"aadhaar_number": "822113513365"},
        },
        people,
        "Application Form",
        source_filename="Co-Applicant/Application/application.pdf",
    )

    assert owner["person_id"] == "coapplicant_1"


def test_trusted_name_match_ignores_honorific_and_ocr_relative_noise() -> None:
    assert name_matches_trusted_person(
        "MR- ★ ANUPKUMAR CHSTAHBHAI SUTHAR",
        {
            "applicant_name": "SUTHAR ANUPKUMAR",
            "father_name": "CHETANBHAI MOHANLAL SUTHAR",
        },
    )


def test_document_index_owner_survives_nameless_continuation_reassignment() -> None:
    page = {
        "page_number": 2,
        "document_type": "CRIF Report",
        "person_id": "coapplicant_2",
        "applicant_role": "coapplicant_2",
        "source_filename": "Co-Applicant/CREDITBUREAU/credit_score.pdf",
        "ocr_text": "ACCOUNT INFORMATION PAYMENT HISTORY OVERDUE",
        "extracted_fields": {
            "_ownership": {
                "person_id": "coapplicant_2",
                "document_scope": "single_person",
                "evidence": ["document_index"],
            }
        },
    }

    # Checklist ownership plus consistency ownership: both passes must keep
    # the group-level resolution on a nameless continuation.
    assign_page_owners([page], {"people": PEERU_FAMILY})
    assign_page_owners([page], {"people": PEERU_FAMILY})

    assert page["person_id"] == "coapplicant_2"
    assert "document_index" in page["extracted_fields"]["_ownership"]["evidence"]


def test_decisive_identity_still_overrides_document_index_owner() -> None:
    page = {
        "page_number": 2,
        "document_type": "PAN",
        "person_id": "coapplicant_2",
        "applicant_role": "coapplicant_2",
        "source_filename": "Co-Applicant/KYC/mixed.pdf",
        "ocr_text": "PAN TSTBB0002T",
        "extracted_fields": {
            "applicant_name": "UNKAR LAL",
            "pan_number": "TSTBB0002T",
            "_ownership": {
                "person_id": "coapplicant_2",
                "document_scope": "single_person",
                "evidence": ["document_index"],
            },
        },
    }

    assign_page_owners([page], {"people": PEERU_FAMILY})

    assert page["person_id"] == "coapplicant_1"
