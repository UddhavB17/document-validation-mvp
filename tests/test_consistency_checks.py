import pytest

from services.checklist_engine import run_checks
from services.consistency_checks import _matches, run_consistency_checks
from services.field_extractor import extract_fields
from services.field_verification import verify_address
from services.page_quality import is_confident_document_match


def _anomaly_text(anomalies: list[dict]) -> str:
    return repr(anomalies)


@pytest.mark.parametrize("field", ["aadhaar_number", "account_number"])
def test_full_identifiers_with_same_last_four_digits_do_not_match(field):
    assert not _matches(field, "123456781234", "987654321234")
    assert _matches(field, "123456781234", "1234 5678 1234")
    assert _matches(field, "123456781234", "XXXX XXXX 1234")
    assert _matches(field, "123456781234", "****1234")
    assert _matches(field, "123456781234", "1234")
    assert not _matches(field, "123456781234", "XXXX XXXX 9999")


def test_multiple_accounts_for_one_person_are_not_cross_document_mismatches() -> None:
    pages = [
        {
            "page_number": 1,
            "document_type": "Passbook",
            "page_type": "digital",
            "person_id": "primary",
            "extracted_fields": {"account_number": "12345678901"},
        },
        {
            "page_number": 2,
            "document_type": "Bank Statement",
            "page_type": "digital",
            "person_id": "primary",
            "extracted_fields": {"account_number": "98765432109"},
        },
    ]
    assert not [
        item
        for item in run_consistency_checks(pages, {})
        if item["rule_id"] == "CROSS_DOCUMENT_ACCOUNT_NUMBER_MISMATCH"
    ]
    trusted = {"people": {"primary": {"account_number": "12345678901"}}}
    assert any(
        item["rule_id"] == "TRUSTED_ACCOUNT_NUMBER_MISMATCH"
        for item in run_consistency_checks(pages, trusted)
    )


def test_name_consistency_ignores_honorifics() -> None:
    pages = [
        {
            "page_number": 1,
            "document_type": "Bank Statement",
            "person_id": "primary",
            "extracted_fields": {"account_holder_name": "Mr. Veeru Lal"},
        }
    ]
    trusted = {"people": {"primary": {"applicant_name": "Veeru Lal"}}}
    assert not [
        item
        for item in run_consistency_checks(pages, trusted)
        if item["rule_id"].startswith(("TRUSTED_", "CROSS_DOCUMENT_"))
        and "NAME_MISMATCH" in item["rule_id"]
    ]


def test_supporting_statement_application_id_is_not_current_loan_id() -> None:
    trusted = {"application_number": "CURRENT-001"}
    statement = {
        "page_number": 1,
        "document_type": "Bank Statement",
        "person_id": "primary",
        "ocr_text": "Previous lender\nLoan Account Statement\nApplication No: OLD-009",
        "page_type": "digital",
        "extracted_fields": {"application_number": "OLD-009"},
    }
    assert not any(
        item["rule_id"] == "TRUSTED_APPLICATION_NUMBER_MISMATCH"
        for item in run_consistency_checks([statement], trusted)
    )
    application = {
        **statement,
        "document_type": "Application Form",
        "ocr_text": "Application No: WRONG-002",
        "extracted_fields": {"application_number": "WRONG-002"},
    }
    assert any(
        item["rule_id"] == "TRUSTED_APPLICATION_NUMBER_MISMATCH"
        for item in run_consistency_checks([application], trusted)
    )


def test_address_consistency_tolerates_minor_ocr_spellings_with_same_pin() -> None:
    pages = [
        {
            "page_number": 1,
            "document_type": "CAM",
            "person_id": "coapplicant_2",
            "extracted_fields": {
                "address": "W/O: Ukar Lal, semah bakhta, Semlibakta, Jhalawar, Suilia, Rajasthan, 326502"
            },
        },
        {
            "page_number": 2,
            "document_type": "Aadhaar",
            "person_id": "coapplicant_2",
            "extracted_fields": {
                "address": "W/O: Ukar Lal, semali bakhta, Semlibakta, Jhalawar, Sulia, Rajasthan, 326502"
            },
        },
    ]
    trusted = {
        "people": {
            "coapplicant_2": {
                "applicant_name": "Sudha Bai",
                "address": "W/O: Ukar Lal",
            }
        }
    }
    assert not [
        item
        for item in run_consistency_checks(pages, trusted)
        if "ADDRESS_MISMATCH" in item["rule_id"]
    ]


def test_aadhaar_xml_appendix_is_excluded_but_primary_page_still_validates() -> None:
    trusted = {
        "people": {
            "coapplicant_1": {
                "applicant_name": "Geeta",
                "pin_code": "335027",
            }
        }
    }
    appendix = page(
        14,
        "Aadhaar",
        "coapplicant_1",
        pin_code="'110003'",
        related_person_name="'Geeta'",
    )
    appendix["ocr_text"] = (
        "Digitally signed e-Aadhaar XML\n"
        '<UidData uid="xxxxxxxx1641"><Poa pc="335027"/></UidData>\n'
        "CN=DS DIGITAL INDIA CORPORATION 3,postalCode=110003"
    )

    anomalies = run_consistency_checks(
        [
            page(13, "Aadhaar", "coapplicant_1", applicant_name="Geeta", pin_code="335027"),
            appendix,
        ],
        trusted,
    )
    assert not any(item["rule_id"] == "TRUSTED_PIN_CODE_MISMATCH" for item in anomalies)

    primary_page_anomalies = run_consistency_checks(
        [page(13, "Aadhaar", "coapplicant_1", applicant_name="Geeta", pin_code="999999")],
        trusted,
    )
    assert any(
        item["rule_id"] == "TRUSTED_PIN_CODE_MISMATCH" and item["page_number"] == 13
        for item in primary_page_anomalies
    )


def test_short_trusted_relationship_address_matches_ocr_variant() -> None:
    result = verify_address(
        "S/O KANMA MEHAR SEMLI BAKTA SEMLI",
        "S/O: Kanha",
    )
    assert result.match is True


def page(number: int, document_type: str, person_id: str | None = None, **fields):
    return {
        "page_number": number,
        "document_type": document_type,
        "page_type": "digital",
        "classification_confidence": 0.99,
        "person_id": person_id,
        "extracted_fields": fields,
    }


def test_normal_case_does_not_run_bt_rows() -> None:
    anomalies = run_checks(
        [page(1, "Application Form"), page(2, "Bank Statement")],
        {"case_type": "Normal Case"},
        {"case_type": "Normal Case"},
        "LAP",
    )
    assert not any(item.get("s_no") in {25, 26, 36} for item in anomalies)


def test_bt_case_runs_all_bt_rows() -> None:
    anomalies = run_checks(
        [page(1, "Application Form"), page(2, "Bank Statement")],
        {"case_type": "BT Case"},
        {"case_type": "BT Case"},
        "LAP",
    )
    assert {25, 26, 36}.issubset({item.get("s_no") for item in anomalies})


def test_pdc_count_is_enforced_for_each_qualifying_person() -> None:
    trusted = {
        "nach_registered": True,
        "people": {
            "primary": {"role": "primary", "applicant_name": "A"},
            "coapplicant_1": {"role": "coapplicant", "applicant_name": "B", "income_earner": True},
        },
    }
    pages = [page(number, "PDC", "coapplicant_1") for number in range(1, 3)]
    pages += [page(10, "Application Form"), page(11, "Bank Statement")]
    anomalies = run_checks(pages, trusted, trusted, "LAP")
    assert any(
        item.get("s_no") == 43 and item.get("person_id") == "coapplicant_1" for item in anomalies
    )


def test_garbage_name_and_masked_dob_do_not_create_trusted_mismatches() -> None:
    trusted = {
        "people": {
            "primary": {
                "applicant_name": "Veeru Lal",
                "date_of_birth": "18-May-1994",
                "address": "S/O: Ambar Lal",
            },
            "coapplicant_2": {
                "applicant_name": "Sudha Bai",
                "date_of_birth": "01-January-1962",
            },
        }
    }
    anomalies = run_consistency_checks(
        [
            page(
                1,
                "Aadhaar",
                "primary",
                applicant_name="c/o , s/o",
                address="Landmark Locality City / District Pin Code",
            ),
            page(2, "Voter ID", "coapplicant_2", date_of_birth="XX/XX/1963"),
            page(3, "CIBIL Report", "primary", applicant_name="SUDHA BAI"),
        ],
        trusted,
    )
    rules = {item["rule_id"] for item in anomalies}
    assert "TRUSTED_APPLICANT_NAME_MISMATCH" not in rules
    assert "TRUSTED_DATE_OF_BIRTH_MISMATCH" not in rules
    assert "TRUSTED_ADDRESS_MISMATCH" not in rules


def test_regional_bilingual_application_form_skips_second_language_anomaly() -> None:
    anomalies = run_consistency_checks(
        [
            {
                "page_number": 1,
                "document_type": "Application Form",
                "page_type": "digital",
                "ocr_text": "Loan Application Form અરજદારનું નામ Veeru Lal",
                "extracted_fields": {"applicant_name": "Veeru Lal"},
            }
        ],
        {"people": {"primary": {"applicant_name": "Veeru Lal"}}},
    )
    assert not any(item["rule_id"] == "APPLICATION_SECOND_LANGUAGE_MISSING" for item in anomalies)


def test_digital_english_hindi_application_satisfies_second_language_rule() -> None:
    anomalies = run_consistency_checks(
        [
            {
                "page_number": 1,
                "document_type": "Application Form",
                "page_type": "digital",
                "ocr_text": "Loan Application Form आवेदक का नाम Veeru Lal",
                "extracted_fields": {"applicant_name": "Veeru Lal"},
            }
        ],
        {"people": {"primary": {"applicant_name": "Veeru Lal"}}},
    )
    assert not any(item["s_no"] == 10 for item in anomalies)


def test_declared_hindi_satisfies_digital_second_language_rule() -> None:
    anomalies = run_consistency_checks(
        [
            {
                "page_number": 1,
                "document_type": "Application Form",
                "page_type": "digital",
                "ocr_text": "Loan Application Form applicant name Veeru Lal",
                "extracted_fields": {
                    "applicant_name": "Veeru Lal",
                    "second_language": "Hindi",
                },
            }
        ],
        {"people": {"primary": {"applicant_name": "Veeru Lal"}}},
    )
    assert not any(item["s_no"] == 10 for item in anomalies)


def test_digital_application_language_evidence_can_span_pages() -> None:
    anomalies = run_consistency_checks(
        [
            {
                "page_number": 1,
                "document_type": "Application Form",
                "page_type": "digital",
                "ocr_text": "Loan Application Form applicant name Veeru Lal",
                "extracted_fields": {"applicant_name": "Veeru Lal"},
            },
            {
                "page_number": 2,
                "document_type": "Application Form",
                "page_type": "digital",
                "ocr_text": "ऋण आवेदन आवेदक का नाम वीरू लाल",
                "extracted_fields": {},
            },
        ],
        {"people": {"primary": {"applicant_name": "Veeru Lal"}}},
    )
    assert not any(item["s_no"] == 10 for item in anomalies)


def test_scanned_application_form_skips_second_language_check() -> None:
    trusted = {"people": {"primary": {"applicant_name": "Veeru Lal"}}}
    anomalies = run_checks(
        [
            {
                "page_number": 79,
                "document_type": "Application Form",
                "page_type": "scanned",
                "ocr_text": "Loan Application Form applicant name Veeru Lal",
                "extracted_fields": {"applicant_name": "Veeru Lal"},
            }
        ],
        trusted,
        trusted,
        "LAP",
    )
    assert not any(item["s_no"] == 10 for item in anomalies)


def test_english_only_digital_application_reports_missing_second_language() -> None:
    anomalies = run_consistency_checks(
        [
            {
                "page_number": 79,
                "document_type": "Application Form",
                "page_type": "digital",
                "ocr_text": "Loan Application Form applicant name Veeru Lal",
                "extracted_fields": {"applicant_name": "Veeru Lal"},
            }
        ],
        {"people": {"primary": {"applicant_name": "Veeru Lal"}}},
    )
    assert any(item["rule_id"] == "APPLICATION_SECOND_LANGUAGE_MISSING" for item in anomalies)


def test_declared_haryanvi_application_satisfies_regional_language_rule() -> None:
    anomalies = run_consistency_checks(
        [
            {
                "page_number": 1,
                "document_type": "Application Form",
                "page_type": "digital",
                "ocr_text": "Loan Application Form आवेदक का नाम Veeru Lal",
                "extracted_fields": {
                    "applicant_name": "Veeru Lal",
                    "second_language": "Haryanvi",
                },
            }
        ],
        {"people": {"primary": {"applicant_name": "Veeru Lal"}}},
    )
    assert not any(item["s_no"] == 10 for item in anomalies)


def test_bhojpuri_provider_metadata_resolves_devanagari_ambiguity() -> None:
    anomalies = run_consistency_checks(
        [
            {
                "page_number": 1,
                "document_type": "Application Form",
                "page_type": "digital",
                "ocr_text": "Loan Application Form आवेदक का नाम Veeru Lal",
                "extracted_fields": {
                    "applicant_name": "Veeru Lal",
                    "_language": {"provider_languages": ["bho"]},
                },
            }
        ],
        {"people": {"primary": {"applicant_name": "Veeru Lal"}}},
    )
    assert not any(item["s_no"] == 10 for item in anomalies)


def test_trusted_template_language_resolves_devanagari_ambiguity() -> None:
    anomalies = run_consistency_checks(
        [
            {
                "page_number": 1,
                "document_type": "Application Form",
                "page_type": "digital",
                "ocr_text": "Loan Application Form आवेदक का नाम Veeru Lal",
                "extracted_fields": {"applicant_name": "Veeru Lal"},
            }
        ],
        {
            "people": {"primary": {"applicant_name": "Veeru Lal"}},
            "application_form_languages": ["English", "Maithili"],
        },
    )
    assert not any(item["s_no"] == 10 for item in anomalies)


def test_name_address_and_bureau_score_consistency() -> None:
    trusted = {
        "people": {
            "primary": {
                "applicant_name": "Veeru Lal",
                "address": "Ward 2 Jhalawar Rajasthan 326001",
            }
        }
    }
    anomalies = run_consistency_checks(
        [
            page(
                1,
                "Aadhaar",
                "primary",
                applicant_name="Veeru Lal",
                address="Ward 2 Jhalawar Rajasthan 326001",
            ),
            page(
                2,
                "Bank Statement",
                "primary",
                account_holder_name="Piru Lal",
                account_number="123456789012",
                address="Ward 9 Kota Rajasthan 324001",
            ),
            page(3, "CIBIL Report", "primary", applicant_name="Veeru Lal", credit_score="950"),
        ],
        trusted,
    )
    rules = {item["rule_id"] for item in anomalies}
    assert "TRUSTED_APPLICANT_NAME_MISMATCH" in rules
    assert "AADHAAR_ADDRESS_MISMATCH" in rules
    assert "BUREAU_SCORE_MISSING" in rules


def test_bureau_valid_first_page_suppresses_continuation_score_flags() -> None:
    trusted = {"people": {"primary": {"applicant_name": "Veeru Lal"}}}
    anomalies = run_consistency_checks(
        [
            {
                **page(1, "CRIF Report", "primary", applicant_name="Veeru Lal", credit_score="786"),
                "ocr_text": "CRIF Credit Information Report For VEERU LAL CRIF HM Score(S): SCORE NAME RANGE SCORE 786",
                "detected_page_number": 1,
            },
            {
                **page(2, "CRIF Report", "primary", credit_score="unknown"),
                "ocr_text": "Account Information continuation",
                "detected_page_number": 1,
            },
        ],
        trusted,
    )
    assert not any(item["rule_id"].startswith("BUREAU_SCORE") for item in anomalies)


def test_bureau_zero_score_is_valid_no_score_exemption() -> None:
    anomalies = run_consistency_checks(
        [
            {
                **page(1, "CRIF Report", "primary", applicant_name="Veeru Lal", credit_score="0"),
                "ocr_text": "CRIF Credit Information Report CRIF HM Score 0",
                "detected_page_number": 1,
            }
        ],
        {"people": {"primary": {"applicant_name": "Veeru Lal"}}},
    )
    assert not any(item["rule_id"].startswith("BUREAU_SCORE") for item in anomalies)


def test_cibil_minus_one_insufficient_history_is_valid_no_score_exemption() -> None:
    anomalies = run_consistency_checks(
        [
            {
                **page(1, "CIBIL Report", "primary", applicant_name="Veeru Lal", credit_score="-1"),
                "ocr_text": "CIBIL SCORE -1 1. Insufficient history to score",
                "detected_page_number": 1,
            }
        ],
        {"people": {"primary": {"applicant_name": "Veeru Lal"}}},
    )
    assert not any(item["rule_id"].startswith("BUREAU_SCORE") for item in anomalies)


def test_crif_blank_score_table_with_zero_accounts_is_valid_no_score_exemption() -> None:
    anomalies = run_consistency_checks(
        [
            {
                **page(1, "CRIF Report", "primary", applicant_name="Veeru Lal"),
                "ocr_text": (
                    "CRIF HM Score(S): SCORE NAME RANGE SCORE Description "
                    "Account Summary Number of Accounts Active Accounts Overdue Accounts "
                    "0 0 0 Group Account Summary"
                ),
                "detected_page_number": 1,
            }
        ],
        {"people": {"primary": {"applicant_name": "Veeru Lal"}}},
    )
    assert not any(item["rule_id"].startswith("BUREAU_SCORE") for item in anomalies)


def test_blank_bureau_score_table_emits_one_document_level_flag() -> None:
    trusted = {"people": {"primary": {"applicant_name": "Sudha Bai"}}}
    anomalies = run_consistency_checks(
        [
            {
                **page(1, "CRIF Report", "primary", applicant_name="Sudha Bai"),
                "ocr_text": "CRIF Credit Information Report For SUDHA BAI CRIF HM Score(S): SCORE NAME RANGE SCORE",
                "detected_page_number": 1,
            },
            {
                **page(2, "CRIF Report", "primary"),
                "ocr_text": "Appendix Section Code Description",
                "detected_page_number": 1,
            },
        ],
        trusted,
    )
    score_flags = [item for item in anomalies if item["rule_id"] == "BUREAU_SCORE_MISSING"]
    assert len(score_flags) == 1
    assert score_flags[0]["page_number"] == 1


def test_repayment_schedule_does_not_satisfy_bank_statement_rules() -> None:
    schedule = page(63, "Bank Statement", "primary")
    schedule["ocr_text"] = "Repayment Schedule under Equated Periodic Instalment EMI (In Rs.)"
    schedule["extracted_fields"] = {
        "statement_period_start": "3007.00",
        "statement_period_end": "238241",
    }
    assert is_confident_document_match(schedule, "Bank Statement") is False


def test_cached_insurance_application_number_is_not_compared_to_loan_dump() -> None:
    insurance = page(
        484,
        "Application Form",
        "primary",
        application_number="0030705",
    )
    insurance["ocr_text"] = (
        "Care Health Insurance Limited IRDAI Registration No. 148\n"
        "Group Care 360 Application Form\n"
        "Proposer Details Nominee Details Policy Period Sum Insured Premium\n"
        "Application No: 0030705"
    )

    anomalies = run_consistency_checks(
        [insurance],
        {
            "application_number": "GJ900000002",
            "people": {"primary": {"applicant_name": "Sutar Ajaykumar"}},
        },
    )

    assert not any(item["rule_id"] == "TRUSTED_APPLICATION_NUMBER_MISMATCH" for item in anomalies)


def test_insurance_page_preserves_explicit_loan_application_number() -> None:
    insurance = page(
        484,
        "Insurance Form",
        "primary",
        application_number="GJ000099999",
    )
    insurance["ocr_text"] = (
        "Care Health Insurance Limited IRDAI Registration No. 148\n"
        "Group Care 360 Application Form\n"
        "Proposer Details Nominee Details Policy Period Sum Insured Premium\n"
        "Loan Application No: GJ000099999\nApplication No: 0030705"
    )

    anomalies = run_consistency_checks(
        [insurance],
        {
            "application_number": "GJ900000002",
            "people": {"primary": {"applicant_name": "Sutar Ajaykumar"}},
        },
    )

    assert any(item["rule_id"] == "TRUSTED_APPLICATION_NUMBER_MISMATCH" for item in anomalies)


def test_health_insurance_form_does_not_satisfy_life_insurance_requirement() -> None:
    health_form = page(484, "Insurance Form", "primary")
    health_form["classification_confidence"] = 0.99
    health_form["ocr_text"] = (
        "Care Health Insurance Limited IRDAI Registration No. 148\n"
        "Group Care 360 Application Form\n"
        "Critical Illness Personal Accident Convalescence Benefit\n"
        "Proposer Nominee Policy Sum Insured Premium"
    )

    assert is_confident_document_match(health_form, "Life Insurance Form") is False


def test_multi_person_cam_rows_are_compared_to_the_correct_people() -> None:
    trusted = {
        "people": {
            "primary": {"applicant_name": "Veeru Lal", "phone_number": "9000000001"},
            "coapplicant_1": {"applicant_name": "Ambar Lal", "phone_number": "9000000002"},
            "coapplicant_2": {"applicant_name": "Sudha Bai", "phone_number": "9000000003"},
        }
    }
    anomalies = run_consistency_checks(
        [
            page(
                1,
                "CAM",
                "primary",
                person_records=[
                    {"applicant_name": "Veeru Lal", "phone_number": "9000000001"},
                    {"applicant_name": "Ambar Lal", "phone_number": "9000000002"},
                    {"applicant_name": "Sudha Bai", "phone_number": "9000000002"},
                ],
            )
        ],
        trusted,
    )
    phone_flags = [item for item in anomalies if item["rule_id"] == "TRUSTED_PHONE_NUMBER_MISMATCH"]
    assert len(phone_flags) == 1
    assert phone_flags[0]["person_id"] == "coapplicant_2"


def test_parent_spouse_relationship_chain_is_consistent() -> None:
    trusted = {
        "people": {
            "primary": {"applicant_name": "Child", "relationship": "self"},
            "coapplicant_1": {"applicant_name": "Mother", "relationship": "mother"},
        }
    }
    anomalies = run_consistency_checks(
        [
            page(
                1, "Aadhaar", "primary", relationship_qualifier="S/O", related_person_name="Father"
            ),
            page(
                2,
                "Aadhaar",
                "coapplicant_1",
                relationship_qualifier="W/O",
                related_person_name="Father",
            ),
        ],
        trusted,
    )
    assert not any(item["rule_id"] == "RELATIONSHIP_QUALIFIER_MISMATCH" for item in anomalies)


def test_short_trusted_address_prefix_matches_full_aadhaar_address() -> None:
    trusted = {"people": {"primary": {"applicant_name": "Veeru Lal", "address": "S/O: Ambar Lal"}}}
    anomalies = run_consistency_checks(
        [page(1, "Aadhaar", "primary", address="S/O: Ambar Lal, Semlibakta, Rajasthan 326502")],
        trusted,
    )
    assert not any(item["rule_id"] == "TRUSTED_ADDRESS_MISMATCH" for item in anomalies)


def test_address_relationship_qualifier_spacing_is_equivalent() -> None:
    trusted = {"people": {"primary": {"applicant_name": "Sudha Bai", "address": "W/O: Ukar Lal"}}}
    anomalies = run_consistency_checks(
        [
            page(
                1,
                "Aadhaar",
                "primary",
                address="WO: Ukar Lal, semali bakhta, Semlibakta, Jhalawar, Sulia, Rajasthan, 326502",
            ),
            page(
                2,
                "Application Form",
                "primary",
                address="W/O: Ukar Lal, semali bakhta, Semlibakta, Sulia, Pachpahar, Jhalawar, Rajasthan, India, 326502",
            ),
        ],
        trusted,
    )
    assert not any(item["rule_id"] == "AADHAAR_ADDRESS_MISMATCH" for item in anomalies)


def test_application_names_are_verified_from_visible_form_text() -> None:
    trusted = {
        "people": {
            "primary": {"applicant_name": "Veeru Lal"},
            "coapplicant_1": {"applicant_name": "Ambar Lal"},
            "coapplicant_2": {"applicant_name": "Sudha Bai"},
        }
    }
    form = page(1, "Application Form", "primary", applicant_name="bad OCR label")
    form["ocr_text"] = "Applicant: Veeru Lal\nCo-applicants: Ambar Lal, Sudha Bai"
    anomalies = run_consistency_checks([form], trusted)
    assert not any(item["rule_id"] == "APPLICATION_NAME_MISMATCH" for item in anomalies)


def test_missing_application_name_is_flagged_when_not_on_form() -> None:
    trusted = {
        "people": {
            "primary": {"applicant_name": "Veeru Lal"},
            "coapplicant_1": {"applicant_name": "Ambar Lal"},
        }
    }
    form = page(1, "Application Form", "primary", applicant_name="Veeru Lal")
    form["ocr_text"] = "Customer Application Form\nApplicant: Veeru Lal"
    anomalies = run_consistency_checks([form], trusted)
    mismatches = [item for item in anomalies if item["rule_id"] == "APPLICATION_NAME_MISMATCH"]
    assert len(mismatches) == 1
    assert mismatches[0]["person_id"] == "coapplicant_1"
    assert mismatches[0]["expected_value"] == "Ambar Lal"
    assert mismatches[0]["found_value"] == "Veeru Lal"


def test_missing_application_names_flag_when_form_has_no_extracted_names() -> None:
    trusted = {
        "people": {
            "primary": {"applicant_name": "Veeru Lal"},
            "coapplicant_1": {"applicant_name": "Ambar Lal"},
        }
    }
    form = page(1, "Application Form", "primary")
    form["ocr_text"] = "Customer Application Form\nSourcing Details\nLoan Product Group"
    anomalies = run_consistency_checks([form], trusted)
    mismatches = [item for item in anomalies if item["rule_id"] == "APPLICATION_NAME_MISMATCH"]
    assert {item["person_id"] for item in mismatches} == {"primary", "coapplicant_1"}
    assert all(item["found_value"] == "Name not extracted" for item in mismatches)


def test_ambar_onkar_name_variant_is_not_a_trusted_mismatch() -> None:
    trusted = {
        "people": {
            "coapplicant_1": {"applicant_name": "Ambar Lal", "address": "S/O: Kanha"},
        }
    }
    anomalies = run_consistency_checks(
        [page(1, "Utility Bill", "coapplicant_1", applicant_name="ONKAR LAL")],
        trusted,
    )
    assert not any("NAME_MISMATCH" in item["rule_id"] for item in anomalies)


def test_glued_ukarlal_address_prefix_matches() -> None:
    result = verify_address(
        "Wo: UkarLal, semali bakhta, Semlibakta, Jhalawar, Sulia, Rajasthan, 326502",
        "W/O : Ukar Lal",
    )
    assert result.match is True


def test_bureau_phone_is_not_compared_to_trusted_phone() -> None:
    trusted = {
        "people": {
            "coapplicant_2": {
                "applicant_name": "Sudha Bai",
                "phone_number": "9000000003",
            }
        }
    }
    anomalies = run_consistency_checks(
        [
            page(
                1,
                "CRIF Report",
                "coapplicant_2",
                applicant_name="SUDHA BAI",
                phone_number="9000000002",
            )
        ],
        trusted,
    )
    assert not any("PHONE" in item["rule_id"] for item in anomalies)


def test_cersai_dob_noise_is_not_a_trusted_mismatch() -> None:
    trusted = {
        "people": {
            "primary": {
                "applicant_name": "Veeru Lal",
                "date_of_birth": "18-May-1994",
                "pan_number": "TSTAA0001T",
            }
        }
    }
    anomalies = run_consistency_checks(
        [
            page(
                1,
                "CERSAI Report",
                "primary",
                applicant_name="VEERU LAL",
                pan_number="TSTAA0001T",
                date_of_birth="1994-12-05",
            )
        ],
        trusted,
    )
    assert not any("DATE_OF_BIRTH" in item["rule_id"] for item in anomalies)


def test_cersai_consistency_compares_debtor_to_matching_coapplicant() -> None:
    trusted = {
        "people": {
            "primary": {"applicant_name": "Veeru Lal", "pan_number": "TSTAA0001T"},
            "coapplicant_1": {"applicant_name": "Ambar Lal", "pan_number": "TSTBB0002T"},
        }
    }
    text = """Debtor Based Search Report
Search Criteria Entered
Name of the Debtor
AMBAR LAL
PAN
TSTBB0002T
Search Output Details
Applicant VEERU LAL PAN TSTAA0001T
"""
    cersai_page = page(1, "CERSAI Report", None, **extract_fields("CERSAI Report", text))
    cersai_page["ocr_text"] = text

    anomalies = run_consistency_checks([cersai_page], trusted)

    assert cersai_page["person_id"] == "coapplicant_1"
    assert not any(
        item["rule_id"].startswith("TRUSTED_") and "MISMATCH" in item["rule_id"]
        for item in anomalies
    )


def test_bureau_apr_month_and_branch_id_are_not_compared_to_loan_data() -> None:
    trusted = {
        "apr": "29.82",
        "branch": "JHALAWAR",
        "people": {"primary": {"applicant_name": "Veeru Lal"}},
    }
    anomalies = run_consistency_checks(
        [page(1, "CIBIL Report", "primary", applicant_name="Veeru Lal", apr="MAR", branch="ID")],
        trusted,
    )
    assert not any("APR" in item["rule_id"] or "BRANCH" in item["rule_id"] for item in anomalies)


def test_address_like_name_candidate_does_not_create_high_name_mismatch() -> None:
    trusted = {"people": {"primary": {"applicant_name": "Veeru Lal"}}}
    anomalies = run_consistency_checks(
        [page(1, "Application Form", "primary", applicant_name="Semali Bakhata")],
        trusted,
    )
    assert not [
        item for item in anomalies if item["severity"] == "HIGH" and "NAME" in item["rule_id"]
    ]
    assert "Semali Bakhata" not in _anomaly_text(anomalies)
    assert not any("NAME_EXTRACTION" in item["rule_id"] for item in anomalies)


def test_relationship_label_name_candidate_does_not_create_cross_document_mismatch() -> None:
    trusted = {"people": {"primary": {"applicant_name": "Veeru Lal"}}}
    anomalies = run_consistency_checks(
        [
            page(1, "Aadhaar", "primary", applicant_name="Veeru Lal"),
            page(2, "Application Form", "primary", applicant_name="C/O"),
            page(3, "Bank Statement", "primary", account_holder_name="S/O"),
            page(4, "PAN", "primary", applicant_name="F/O"),
        ],
        trusted,
    )
    assert not any(
        item["rule_id"] == "CROSS_DOCUMENT_APPLICANT_NAME_MISMATCH" for item in anomalies
    )
    assert not any(item["rule_id"] == "TRUSTED_APPLICANT_NAME_MISMATCH" for item in anomalies)
    assert "C/O" not in _anomaly_text(anomalies)
    assert "S/O" not in _anomaly_text(anomalies)
    assert "F/O" not in _anomaly_text(anomalies)


def test_inherited_unknown_page_name_without_anchor_is_manual_review_not_high_mismatch() -> None:
    trusted = {"people": {"primary": {"applicant_name": "Sita Kumar"}}}
    anomalies = run_consistency_checks(
        [
            {
                "page_number": 2,
                "document_type": "Application Form",
                "person_id": "primary",
                "extracted_fields": {
                    "applicant_name": "Ramesh Kumar",
                    "_identity_extraction_reliable": False,
                },
            }
        ],
        trusted,
    )
    assert not any(item["severity"] == "HIGH" and "NAME" in item["rule_id"] for item in anomalies)
    assert "Ramesh Kumar" not in _anomaly_text(anomalies)
    assert not any("NAME_EXTRACTION" in item["rule_id"] for item in anomalies)


def test_duplicated_trusted_name_token_is_not_a_mismatch() -> None:
    # Trusted dumps sometimes repeat a token ("Sandeep SANDEEP").
    trusted = {"people": {"primary": {"applicant_name": "Sandeep SANDEEP"}}}
    anomalies = run_consistency_checks(
        [page(1, "Aadhaar", "primary", applicant_name="Sandeep")],
        trusted,
    )
    assert not any("NAME_MISMATCH" in item["rule_id"] for item in anomalies)


def test_name_with_father_tokens_is_not_a_trusted_mismatch() -> None:
    # "Given + father's name + surname" identifies the same person under
    # Indian naming conventions as the trusted "Surname Given" form.
    trusted = {
        "people": {
            "primary": {
                "applicant_name": "Sutar Ajaykumar",
                "father_name": "Kiranbhai Sohanlal Sutar",
            }
        }
    }
    anomalies = run_consistency_checks(
        [page(1, "PAN", "primary", applicant_name="Ajaykumar Kiranbhai Sutar")],
        trusted,
    )
    assert not any("NAME_MISMATCH" in item["rule_id"] for item in anomalies)


def test_reordered_name_tokens_are_not_a_trusted_mismatch() -> None:
    trusted = {"people": {"primary": {"applicant_name": "Sutar Ajaykumar"}}}
    anomalies = run_consistency_checks(
        [page(1, "PAN", "primary", applicant_name="Ajaykumar Sutar")],
        trusted,
    )
    assert not any("NAME_MISMATCH" in item["rule_id"] for item in anomalies)


def test_unassigned_person_fields_skip_trusted_checks_in_single_person_manifest() -> None:
    # A guarantor's document left unassigned must not be compared against the
    # sole trusted person.
    trusted = {"people": {"primary": {"applicant_name": "Sutar Ajaykumar"}}}
    guarantor_page = page(1, "Aadhaar", None, applicant_name="Parmar Naresh Ramanbhai")
    guarantor_page["person_id"] = "unassigned"
    anomalies = run_consistency_checks([guarantor_page], trusted)
    assert not any(
        "TRUSTED_" in item["rule_id"] and "MISMATCH" in item["rule_id"] for item in anomalies
    )


def test_unassigned_foreign_pan_is_not_repaired_to_single_primary() -> None:
    trusted = {
        "people": {
            "primary": {
                "applicant_name": "Sutar Ajaykumar",
                "pan_number": "TSTPA1051Z",
                "date_of_birth": "18-Jun-2001",
            }
        }
    }
    foreign = page(
        519,
        "PAN",
        "unassigned",
        applicant_name="SUTAR BHARATIBEN AJAYKUMAR",
        pan_number="TSTPA1053Z",
        date_of_birth="22-08-2000",
    )
    anomalies = run_consistency_checks([foreign], trusted)
    assert not [
        item
        for item in anomalies
        if item["rule_id"]
        in {
            "TRUSTED_APPLICANT_NAME_MISMATCH",
            "TRUSTED_PAN_NUMBER_MISMATCH",
            "TRUSTED_DATE_OF_BIRTH_MISMATCH",
        }
    ]
    assert foreign["person_id"] == "unassigned"


def test_unresolved_second_person_record_is_not_compared_to_primary() -> None:
    trusted = {
        "people": {
            "primary": {
                "applicant_name": "SUTAR AJAYKUMAR",
                "pan_number": "TSTPA1051Z",
            }
        }
    }
    form = page(
        1,
        "Application Form",
        "primary",
        person_records=[
            {
                "_resolved_person_id": "primary",
                "applicant_name": "SUTAR AJAYKUMAR",
                "pan_number": "TSTPA1051Z",
            },
            {
                "applicant_name": "SUTAR BHARATIBEN AJAYKUMAR",
                "pan_number": "TSTPA1053Z",
                "aadhaar_last4": "8196",
            },
        ],
        applicant_name="SUTAR BHARATIBEN AJAYKUMAR",
        pan_number="TSTPA1053Z",
    )
    anomalies = run_consistency_checks([form], trusted)
    assert not [
        item
        for item in anomalies
        if item["rule_id"].startswith("TRUSTED_")
        and str(item.get("found_value")) in {"SUTAR BHARATIBEN AJAYKUMAR", "TSTPA1053Z", "8196"}
    ]


def test_flat_guarantor_section_without_person_rows_is_not_compared_to_primary() -> None:
    trusted = {
        "people": {
            "primary": {
                "applicant_name": "SUTAR AJAYKUMAR",
                "pan_number": "TSTPA1051Z",
                "address": "MODIVAS HARNIYAV AHMEDABAD 382435",
            }
        }
    }
    form = page(
        24,
        "Application Form",
        "primary",
        applicant_name="PARMAR NARESH RAMANBHAI",
        pan_number="TSTPA1052Z",
        current_address="1739 INDIRA NAGAR LAMBHA AHMEDABAD 382405",
        person_records=[],
    )
    form["ocr_text"] = "GUARANTOR DETAILS\nPARMAR NARESH RAMANBHAI\nTSTPA1052Z"
    form["source_document_id"] = "application-1"
    continuation = page(
        25,
        "Application Form",
        "primary",
        pan_number="TSTPA1052Z",
        person_records=[],
    )
    continuation["ocr_text"] = "PARMAR NARESH RAMANBHAI\nTSTPA1052Z\nREFERENCE DETAILS"
    continuation["source_document_id"] = "application-1"

    anomalies = run_consistency_checks([form, continuation], trusted)

    assert not any(item["rule_id"].startswith("TRUSTED_") for item in anomalies)
    assert not any(item["rule_id"] == "AADHAAR_ADDRESS_MISMATCH" for item in anomalies)


def test_guarantor_addresses_are_excluded_from_borrower_address_checks() -> None:
    trusted = {
        "people": {
            "primary": {
                "role": "primary",
                "applicant_name": "Kala Singh",
                "address": "27 F Kaminpura Ganganagar Rajasthan 335027",
            },
            "coapplicant_1": {
                "role": "coapplicant",
                "applicant_name": "Sandeep Singh",
                "address": "11 Chak 5 Sri Ganganagar Rajasthan 335001",
            },
            "guarantor_1": {
                "role": "guarantor",
                "applicant_name": "Ramesh Kumar",
            },
        }
    }
    pages = [
        page(1, "Aadhaar", "primary", address="27 F Kaminpura Ganganagar Rajasthan 335027"),
        page(
            2,
            "Application Form",
            "coapplicant_1",
            address="11 Chak 5 Sri Ganganagar Rajasthan 335001",
        ),
        page(3, "Aadhaar", "guarantor_1", address="99 Unrelated Road Jaipur Rajasthan 302001"),
        page(
            4,
            "Application Form",
            "guarantor_1",
            address="12 Different Colony Kota Rajasthan 324001",
        ),
    ]

    anomalies = run_consistency_checks(pages, trusted)

    assert not any("ADDRESS_MISMATCH" in item["rule_id"] for item in anomalies)


def test_flat_primary_application_without_person_rows_still_reports_mismatch() -> None:
    trusted = {
        "people": {
            "primary": {
                "applicant_name": "RAMESH KUMAR",
                "pan_number": "ABCDE1234F",
            }
        }
    }
    form = page(
        1,
        "Application Form",
        "primary",
        applicant_name="RAMESH KUMAR",
        pan_number="TSTPA7025Z",
        person_records=[],
    )
    form["ocr_text"] = "LOAN APPLICATION FORM\nApplicant Name RAMESH KUMAR\nPAN TSTPA7025Z"

    anomalies = run_consistency_checks([form], trusted)

    assert any(item["rule_id"] == "TRUSTED_PAN_NUMBER_MISMATCH" for item in anomalies)


def test_flat_cam_application_details_without_person_rows_still_reports_mismatch() -> None:
    trusted = {
        "people": {
            "primary": {
                "applicant_name": "RAMESH KUMAR",
                "phone_number": "9000000001",
            }
        }
    }
    cam = page(
        1,
        "CAM",
        "primary",
        applicant_name="RAMESH KUMAR",
        phone_number="9000000002",
        person_records=[],
    )
    cam["ocr_text"] = "CREDIT APPROVAL MEMO\nAPPLICATION DETAILS\nName\nRAMESH KUMAR"

    anomalies = run_consistency_checks([cam], trusted)

    assert any(item["rule_id"] == "TRUSTED_PHONE_NUMBER_MISMATCH" for item in anomalies)


def test_global_security_section_resets_coapplicant_role_state() -> None:
    trusted = {
        "people": {
            "primary": {
                "applicant_name": "RAMESH KUMAR",
                "account_number": "111111111111",
            }
        }
    }
    coapp = page(
        1,
        "Application Form",
        "primary",
        applicant_name="SITA KUMAR",
        person_records=[],
    )
    coapp["ocr_text"] = "CO-APPLICANT PERSONAL DETAILS\nName SITA KUMAR"
    coapp["source_document_id"] = "application-1"
    security = page(
        2,
        "Application Form",
        "primary",
        account_number="999999999999",
        person_records=[],
    )
    security["ocr_text"] = "DETAILS OF SECURITY OFFERED-PROPERTY\nBANK ACCOUNT DETAILS"
    security["source_document_id"] = "application-1"

    anomalies = run_consistency_checks([coapp, security], trusted)

    assert any(item["rule_id"] == "TRUSTED_ACCOUNT_NUMBER_MISMATCH" for item in anomalies)


def test_bank_branch_is_not_compared_to_loan_branch_but_loan_branch_is() -> None:
    trusted = {
        "branch": "AHMEDABAD-1",
        "people": {"primary": {"applicant_name": "Sutar Ajaykumar"}},
    }
    bank_only = run_consistency_checks(
        [
            page(
                528,
                "Passbook",
                "primary",
                account_holder_name="AJAYKUMAR KIRANBHAI SUTAR",
                branch="HARANIYAV",
            )
        ],
        trusted,
    )
    assert not any("BRANCH_MISMATCH" in item["rule_id"] for item in bank_only)

    loan_doc = run_consistency_checks(
        [page(1, "Sanction Letter", "primary", branch="SURAT-2")],
        trusted,
    )
    assert any(item["rule_id"] == "TRUSTED_BRANCH_MISMATCH" for item in loan_doc)


def test_trusted_permanent_and_communication_addresses_are_valid_variants() -> None:
    trusted = {
        "people": {
            "primary": {
                "applicant_name": "Sutar Ajaykumar",
                "permanent_address": "MODIVAS GAM HARNIYAV AHMEDABAD 382435",
                "communication_address": "B 402 PANDIT DINDAYAL 2 HATHIJAN AHMEDABAD 382445",
            }
        }
    }
    anomalies = run_consistency_checks(
        [
            page(1, "Aadhaar", "primary", address="MODIVAS GAM HARNIYAV AHMEDABAD GUJARAT 382435"),
            page(
                2,
                "Application Form",
                "primary",
                current_address="B-402 PANDIT DINDAYAL-2 HATHIJAN AHMEDABAD 382445",
            ),
            page(
                3,
                "Utility Bill",
                "primary",
                address="B 402 PANDIT DINDAYAL 2 HATHIJAN AHMEDABAD 382445",
            ),
        ],
        trusted,
    )
    assert not [item for item in anomalies if "ADDRESS_MISMATCH" in item["rule_id"]]

    unrelated = run_consistency_checks(
        [
            page(1, "Aadhaar", "primary", address="MODIVAS GAM HARNIYAV AHMEDABAD 382435"),
            page(3, "Utility Bill", "primary", address="99 UNKNOWN ROAD SURAT 395003"),
        ],
        trusted,
    )
    # ws-f accuracy: the blanket utility-bill skip is replaced by the page
    # eligibility gate, and utility bills legitimately carry addresses — so a
    # genuinely conflicting utility-bill address now surfaces (page 3).
    assert any(
        "ADDRESS_MISMATCH" in item["rule_id"] and item["page_number"] == 3
        for item in unrelated
    )


def test_utility_address_is_not_compared_for_coapplicant() -> None:
    trusted = {
        "communication_address": "B 402 PANDIT DINDAYAL 2 HATHIJAN AHMEDABAD 382445",
        "people": {
            "primary": {
                "role": "primary",
                "applicant_name": "Sutar Ajaykumar",
            },
            "coapplicant_1": {
                "role": "coapplicant",
                "applicant_name": "Sutar Bharatiben",
                "permanent_address": "17 SHANTI NAGAR VATVA AHMEDABAD 382440",
            },
        },
    }
    anomalies = run_consistency_checks(
        [
            page(
                1,
                "Utility Bill",
                "coapplicant_1",
                address="B 402 PANDIT DINDAYAL 2 HATHIJAN AHMEDABAD 382445",
            )
        ],
        trusted,
    )

    # ws-f accuracy: utility bills legitimately carry addresses, so the
    # co-applicant's conflicting utility-bill address is now compared.
    assert any("ADDRESS_MISMATCH" in item["rule_id"] for item in anomalies)


def test_relative_token_tolerance_applies_only_to_holder_name() -> None:
    trusted = {
        "people": {
            "primary": {
                "applicant_name": "Sutar Ajaykumar",
                "father_name": "Kiranbhai Sutar",
                "pan_number": "TSTPA1051Z",
            }
        }
    }
    anomalies = run_consistency_checks(
        [
            page(
                1,
                "PAN",
                "primary",
                applicant_name="Ajaykumar Kiranbhai Sutar",
                father_name="Ajaykumar Kiranbhai Sutar",
                pan_number="TSTPA1051Z",
            )
        ],
        trusted,
    )

    assert not any(item["rule_id"] == "TRUSTED_APPLICANT_NAME_MISMATCH" for item in anomalies)
    assert any(item["rule_id"] == "TRUSTED_FATHER_NAME_MISMATCH" for item in anomalies)


def test_utility_flat_number_is_not_compared() -> None:
    trusted = {
        "people": {
            "primary": {
                "applicant_name": "Sutar Ajaykumar",
                "communication_address": (
                    "Flat No. B-402 Pandit Dindayal 2 Hathijan Ahmedabad 382445"
                ),
            }
        }
    }
    anomalies = run_consistency_checks(
        [
            page(
                1,
                "Utility Bill",
                "primary",
                address="B 403 Pandit Dindayal 2 Hathijan Ahmedabad 382445",
            )
        ],
        trusted,
    )

    # ws-f accuracy: the eligibility gate replaced the blanket utility-bill
    # skip, so an explicit flat-number conflict (B-403 vs B-402) now surfaces.
    assert any("ADDRESS_MISMATCH" in item["rule_id"] for item in anomalies)


def test_equivalent_explicit_flat_number_formats_still_match() -> None:
    trusted = {
        "people": {
            "primary": {
                "applicant_name": "Sutar Ajaykumar",
                "communication_address": (
                    "Flat No. B-402 Pandit Dindayal 2 Hathijan Ahmedabad 382445"
                ),
            }
        }
    }
    anomalies = run_consistency_checks(
        [
            page(
                1,
                "Utility Bill",
                "primary",
                address="B 402 Pandit Dindayal 2 Hathijan Ahmedabad 382445",
            )
        ],
        trusted,
    )

    assert not any("ADDRESS_MISMATCH" in item["rule_id"] for item in anomalies)


def test_aadhaar_relation_name_and_masked_bureau_grid_are_not_identity_evidence() -> None:
    aadhaar = page(
        643,
        "Aadhaar",
        "primary",
        applicant_name="Sutar Kiranbhai",
        related_person_name="Sutar Kiranbhai",
        relationship_qualifier="S/O",
        aadhaar_number="822113513365",
    )
    bureau = page(762, "CRIF Report", "primary", crif_score="'900/XXX'")
    anomalies = run_consistency_checks(
        [aadhaar, bureau],
        {
            "people": {
                "primary": {
                    "applicant_name": "Sutar Ajaykumar",
                    "aadhaar_last4": "3365",
                    "crif_score": 628,
                }
            }
        },
    )
    assert not any("NAME_MISMATCH" in item["rule_id"] for item in anomalies)
    assert not any("CRIF_SCORE_MISMATCH" in item["rule_id"] for item in anomalies)


def test_reliable_name_mismatch_requires_identity_affidavit() -> None:
    anomalies = run_consistency_checks(
        [
            page(1, "PAN", "primary", applicant_name="Ramesh Kumar", pan_number="ABCDE1234F"),
            page(
                2, "KYC Card Photo", "primary", applicant_name="Ramesh Lal", pan_number="ABCDE1234F"
            ),
        ],
        {"people": {"primary": {"applicant_name": "Ramesh Kumar", "pan_number": "ABCDE1234F"}}},
    )

    assert any(item["rule_id"] == "IDENTITY_AFFIDAVIT_MISSING" for item in anomalies)


def test_overlapping_validations_keep_each_applications_age_reference(monkeypatch) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    import services.consistency_checks as checks

    both_ready = Barrier(2)
    original = checks._identity_affidavit_checks

    def check_after_both_validations_start(*args):
        both_ready.wait(timeout=10)
        return original(*args)

    monkeypatch.setattr(checks, "_identity_affidavit_checks", check_after_both_validations_start)

    def validate(reference_date):
        anomalies = run_consistency_checks(
            [page(
                1, "PAN", "primary", applicant_name="Ramesh Kumar",
                pan_number="ABCDE1234F", date_of_birth="01-January-2005",
            )],
            {
                "reference_date": reference_date,
                "people": {"primary": {
                    "applicant_name": "Ramesh Kumar",
                    "pan_number": "ABCDE1234F",
                    "date_of_birth": "01-January-1990",
                }},
            },
        )
        assert any(item["rule_id"] == "TRUSTED_DATE_OF_BIRTH_MISMATCH" for item in anomalies)
        return any(item["rule_id"] == "IDENTITY_AFFIDAVIT_MISSING" for item in anomalies)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(validate, ["2026-01-01", "2010-01-01"]))
    assert results == [True, False]


def test_dual_name_affidavit_resolves_affidavit_requirement() -> None:
    affidavit = page(3, "Affidavit", "primary")
    affidavit["ocr_text"] = (
        "AFFIDAVIT For Dual Name or Mismatch of Name. My correct name is Ramesh Kumar. "
        "My name as per Aadhaar is Ramesh Lal."
    )
    anomalies = run_consistency_checks(
        [
            page(1, "PAN", "primary", applicant_name="Ramesh Kumar", pan_number="ABCDE1234F"),
            page(
                2, "KYC Card Photo", "primary", applicant_name="Ramesh Lal", pan_number="ABCDE1234F"
            ),
            affidavit,
        ],
        {"people": {"primary": {"applicant_name": "Ramesh Kumar", "pan_number": "ABCDE1234F"}}},
    )

    assert not any(item["rule_id"] == "IDENTITY_AFFIDAVIT_MISSING" for item in anomalies)


def test_address_layout_ocr_matches_unit_and_rural_locality_variants() -> None:
    assert _matches(
        "address",
        "B 402 PANDIT DINDAYAL-2 NR V NAGAR HATHIJAN AHMEDABAD 382445",
        "B 402 NAMAR PANDIT HATHIJAN DINDAJAL-2 NRV AHMEDABAD 352445",
    )
    assert _matches(
        "address",
        "MODIVAS HARNIYAV MODIVAS AHMEDABAD GUJARAT INDIA 382435",
        "MODIVAS HARNIYAU HARNSLAV AHMEDABAD 382435",
    )


def test_mother_spouse_chain_tolerates_transliteration_and_omitted_surname() -> None:
    anomalies = run_consistency_checks(
        [
            page(
                1,
                "Aadhaar",
                "primary",
                applicant_name="Mannu Lal Deena",
                relationship_qualifier="S/O",
                related_person_name="Deeka Ram Deena",
            ),
            page(
                2,
                "Aadhaar",
                "coapplicant_2",
                applicant_name="Sukumani Devi",
                relationship_qualifier="W/O",
                related_person_name="Dika Ram",
            ),
        ],
        {
            "people": {
                "primary": {"applicant_name": "Mannu Lal Deena"},
                "coapplicant_2": {
                    "applicant_name": "Sukumani Devi",
                    "relationship": "mother",
                },
            }
        },
    )

    assert not any(item["rule_id"] == "RELATIONSHIP_QUALIFIER_MISMATCH" for item in anomalies)


def test_non_loan_tax_amount_cannot_anchor_cross_document_loan_amount() -> None:
    application = page(
        425,
        "Application Form",
        "primary",
        applicant_name="Mannu Lal Deena",
        loan_amount="610000",
    )
    application["ocr_text"] = (
        "Customer Application Form Applicant Name Mannu Lal Deena Loan Amount 610000"
    )
    anomalies = run_consistency_checks(
        [
            page(61, "GST Certificate", "primary", loan_amount="1397.75"),
            application,
        ],
        {
            "people": {
                "primary": {
                    "applicant_name": "Mannu Lal Deena",
                    "loan_amount": "610000",
                }
            }
        },
    )

    assert not any("LOAN_AMOUNT_MISMATCH" in item["rule_id"] for item in anomalies)


def test_authority_boilerplate_and_empty_guarantor_heading_are_not_addresses() -> None:
    anomalies = run_consistency_checks(
        [
            page(
                849,
                "Aadhaar",
                "primary",
                address=(
                    "भारतीय विशिष्ट पहचान प्राधिकरण Unique Identification Authority of India "
                    "S/O Deeka Ram Deena 44 Ward 02 Deoli Rajasthan 304023"
                ),
            ),
            page(
                850,
                "Aadhaar",
                "primary",
                address="S/O Deeka Ram Deena 44 Ward 02 Deoli Rajasthan 304023",
            ),
            page(
                431,
                "Application Form",
                "primary",
                permanent_address="GUARANTOR EMPLOYEMENT/BUSINESS DETAILS",
            ),
        ],
        {
            "people": {
                "primary": {
                    "applicant_name": "Mannu Lal Deena",
                    "address": "44 Ward 02 Deoli Rajasthan 304023",
                }
            }
        },
    )

    assert not any("ADDRESS_MISMATCH" in item["rule_id"] for item in anomalies)


def test_hindi_identity_affidavit_is_used_even_if_page_was_typed_as_aadhaar() -> None:
    affidavit = page(391, "Aadhaar", "coapplicant_3")
    affidavit["ocr_text"] = (
        "NOTARY\nशपथ-पत्र\nमैं रसमी दीना सशपथ बयान करती हूं कि आधार कार्ड में "
        "जन्म दिनांक 02/03/1993 व नाम RASMEE DEENA सही एवं मान्य है तथा "
        "पेन कार्ड में जन्म दिनांक 01/01/1993 व नाम RASAMI DEENA अलग है।\n"
        "सत्यापन\nहस्ताक्षर शपथग्रहिता"
    )
    anomalies = run_consistency_checks(
        [
            page(
                18,
                "PAN",
                "coapplicant_3",
                applicant_name="RASAMI DEENA",
                pan_number="TSTPA1040Z",
            ),
            affidavit,
        ],
        {
            "people": {
                "coapplicant_3": {
                    "applicant_name": "RASMEE DEENA",
                    "pan_number": "TSTPA1040Z",
                }
            }
        },
    )

    assert any(item["rule_id"] == "TRUSTED_APPLICANT_NAME_MISMATCH" for item in anomalies)
    assert not any(item["rule_id"] == "IDENTITY_AFFIDAVIT_MISSING" for item in anomalies)


def test_anomaly_points_to_page_where_data_actually_exists() -> None:
    trusted = {
        "people": {
            "primary": {
                "applicant_name": "AJAYKUMAR SUTAR",
                "address": "44 Ward 2 Deoli Rajasthan 304023",
            },
            "coapplicant_1": {
                "applicant_name": "Bharatiben Sutar",
                "address": "81 Modi Vas Harnivav Gujarat 382435",
            },
        }
    }

    p18 = page(18, "Application Form", "primary")
    p18["source_document_id"] = "app-doc-1"
    p18["ocr_text"] = "MS FINCAP OFFICE ADDRESS"

    p20 = page(20, "Application Form", "primary")
    p20["source_document_id"] = "app-doc-1"
    p20["ocr_text"] = "Permanent Address: 44 Ward 2 Deoli Rajasthan 304023"

    p22 = page(22, "Application Form", "primary")
    p22["source_document_id"] = "app-doc-1"
    p22["ocr_text"] = "Coapplicant Address: 81 Modi Vas Harnivav Gujarat 382435"

    extracted_records = [
        {
            "_resolved_person_id": "primary",
            "applicant_name": "AJAYKUMAR SUTAR",
            "permanent_address": "44 Ward 2 Deoli Rajasthan 304023",
        },
        {
            "_resolved_person_id": "coapplicant_1",
            "applicant_name": "Bharatiben Sutar",
            "permanent_address": "81 Modi Vas Harnivav Gujarat 382435",
        },
    ]
    p18["extracted_fields"] = {"person_records": extracted_records}
    p20["extracted_fields"] = {"person_records": extracted_records}
    p22["extracted_fields"] = {"person_records": extracted_records}

    aadhaar_primary = page(
        100, "Aadhaar", "primary", address="99 Unrelated Road Jaipur Rajasthan 302001"
    )
    aadhaar_coapplicant = page(
        101, "Aadhaar", "coapplicant_1", address="77 Different Street Kota Rajasthan 324001"
    )

    anomalies = run_consistency_checks(
        [p18, p20, p22, aadhaar_primary, aadhaar_coapplicant], trusted
    )

    primary_mismatches = [
        item
        for item in anomalies
        if item["rule_id"] == "AADHAAR_ADDRESS_MISMATCH" and item["person_id"] == "primary"
    ]
    assert len(primary_mismatches) >= 1
    assert all(item["page_number"] == 20 for item in primary_mismatches)

    coapplicant_mismatches = [
        item
        for item in anomalies
        if item["rule_id"] == "AADHAAR_ADDRESS_MISMATCH" and item["person_id"] == "coapplicant_1"
    ]
    assert len(coapplicant_mismatches) >= 1
    assert all(item["page_number"] == 22 for item in coapplicant_mismatches)
