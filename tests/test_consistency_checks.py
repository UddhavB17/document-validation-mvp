from services.checklist_engine import run_checks
from services.consistency_checks import run_consistency_checks
from services.field_verification import verify_address


def test_name_consistency_ignores_honorifics() -> None:
    pages = [{
        "page_number": 1,
        "document_type": "Bank Statement",
        "person_id": "primary",
        "extracted_fields": {"account_holder_name": "Mr. Peeru Lal"},
    }]
    trusted = {"people": {"primary": {"applicant_name": "Peeru Lal"}}}
    assert not [
        item for item in run_consistency_checks(pages, trusted)
        if item["rule_id"].startswith(("TRUSTED_", "CROSS_DOCUMENT_"))
        and "NAME_MISMATCH" in item["rule_id"]
    ]


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
                "applicant_name": "Radha Bai",
                "address": "W/O: Ukar Lal",
            }
        }
    }
    assert not [
        item for item in run_consistency_checks(pages, trusted)
        if "ADDRESS_MISMATCH" in item["rule_id"]
    ]


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
    assert any(item.get("s_no") == 43 and item.get("person_id") == "coapplicant_1" for item in anomalies)


def test_garbage_name_and_masked_dob_do_not_create_trusted_mismatches() -> None:
    trusted = {
        "people": {
            "primary": {
                "applicant_name": "Peeru Lal",
                "date_of_birth": "18-May-1994",
                "address": "S/O: Unkar Lal",
            },
            "coapplicant_2": {
                "applicant_name": "Radha Bai",
                "date_of_birth": "01-January-1962",
            },
        }
    }
    anomalies = run_consistency_checks(
        [
            page(1, "Aadhaar", "primary", applicant_name="c/o , s/o", address="Landmark Locality City / District Pin Code"),
            page(2, "Voter ID", "coapplicant_2", date_of_birth="XX/XX/1963"),
            page(3, "CIBIL Report", "primary", applicant_name="RADHA BAI"),
        ],
        trusted,
    )
    rules = {item["rule_id"] for item in anomalies}
    assert "TRUSTED_APPLICANT_NAME_MISMATCH" not in rules
    assert "TRUSTED_DATE_OF_BIRTH_MISMATCH" not in rules
    assert "TRUSTED_ADDRESS_MISMATCH" not in rules


def test_bilingual_application_form_skips_second_language_anomaly() -> None:
    anomalies = run_consistency_checks(
        [
            {
                "page_number": 1,
                "document_type": "Application Form",
                "ocr_text": "Loan Application Form आवेदक का नाम Peeru Lal",
                "extracted_fields": {"applicant_name": "Peeru Lal"},
            }
        ],
        {"people": {"primary": {"applicant_name": "Peeru Lal"}}},
    )
    assert not any(item["rule_id"] == "APPLICATION_SECOND_LANGUAGE_MISSING" for item in anomalies)


def test_name_address_and_bureau_score_consistency() -> None:
    trusted = {
        "people": {
            "primary": {
                "applicant_name": "Peeru Lal",
                "address": "Ward 2 Jhalawar Rajasthan 326001",
            }
        }
    }
    anomalies = run_consistency_checks(
        [
            page(1, "Aadhaar", "primary", applicant_name="Peeru Lal", address="Ward 2 Jhalawar Rajasthan 326001"),
            page(2, "Bank Statement", "primary", account_holder_name="Piru Lal", address="Ward 9 Kota Rajasthan 324001"),
            page(3, "CIBIL Report", "primary", applicant_name="Peeru Lal", credit_score="950"),
        ],
        trusted,
    )
    rules = {item["rule_id"] for item in anomalies}
    assert "TRUSTED_APPLICANT_NAME_MISMATCH" in rules
    assert "AADHAAR_ADDRESS_MISMATCH" in rules
    assert "BUREAU_SCORE_INVALID" in rules


def test_multi_person_cam_rows_are_compared_to_the_correct_people() -> None:
    trusted = {
        "people": {
            "primary": {"applicant_name": "Peeru Lal", "phone_number": "8107058694"},
            "coapplicant_1": {"applicant_name": "Unkar Lal", "phone_number": "9509341692"},
            "coapplicant_2": {"applicant_name": "Radha Bai", "phone_number": "7339781668"},
        }
    }
    anomalies = run_consistency_checks(
        [
            page(
                1,
                "CAM",
                "primary",
                person_records=[
                    {"applicant_name": "Peeru Lal", "phone_number": "8107058694"},
                    {"applicant_name": "Unkar Lal", "phone_number": "9509341692"},
                    {"applicant_name": "Radha Bai", "phone_number": "9509341692"},
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
            page(1, "Aadhaar", "primary", relationship_qualifier="S/O", related_person_name="Father"),
            page(2, "Aadhaar", "coapplicant_1", relationship_qualifier="W/O", related_person_name="Father"),
        ],
        trusted,
    )
    assert not any(item["rule_id"] == "RELATIONSHIP_QUALIFIER_MISMATCH" for item in anomalies)


def test_short_trusted_address_prefix_matches_full_aadhaar_address() -> None:
    trusted = {
        "people": {"primary": {"applicant_name": "Peeru Lal", "address": "S/O: Unkar Lal"}}
    }
    anomalies = run_consistency_checks(
        [page(1, "Aadhaar", "primary", address="S/O: Unkar Lal, Semlibakta, Rajasthan 326502")],
        trusted,
    )
    assert not any(item["rule_id"] == "TRUSTED_ADDRESS_MISMATCH" for item in anomalies)


def test_address_relationship_qualifier_spacing_is_equivalent() -> None:
    trusted = {
        "people": {"primary": {"applicant_name": "Radha Bai", "address": "W/O: Ukar Lal"}}
    }
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
            "primary": {"applicant_name": "Peeru Lal"},
            "coapplicant_1": {"applicant_name": "Unkar Lal"},
            "coapplicant_2": {"applicant_name": "Radha Bai"},
        }
    }
    form = page(1, "Application Form", "primary", applicant_name="bad OCR label")
    form["ocr_text"] = "Applicant: Peeru Lal\nCo-applicants: Unkar Lal, Radha Bai"
    anomalies = run_consistency_checks([form], trusted)
    assert not any(item["rule_id"] == "APPLICATION_NAME_MISMATCH" for item in anomalies)


def test_unkar_onkar_name_variant_is_not_a_trusted_mismatch() -> None:
    trusted = {
        "people": {
            "coapplicant_1": {"applicant_name": "Unkar Lal", "address": "S/O: Kanha"},
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
                "applicant_name": "Radha Bai",
                "phone_number": "7339781668",
            }
        }
    }
    anomalies = run_consistency_checks(
        [page(1, "CRIF Report", "coapplicant_2", applicant_name="RADHA BAI", phone_number="9509341692")],
        trusted,
    )
    assert not any("PHONE" in item["rule_id"] for item in anomalies)


def test_cersai_dob_noise_is_not_a_trusted_mismatch() -> None:
    trusted = {
        "people": {
            "primary": {
                "applicant_name": "Peeru Lal",
                "date_of_birth": "18-May-1994",
                "pan_number": "BCXPL9010K",
            }
        }
    }
    anomalies = run_consistency_checks(
        [page(1, "CERSAI Report", "primary", applicant_name="PEERU LAL", pan_number="BCXPL9010K", date_of_birth="1994-12-05")],
        trusted,
    )
    assert not any("DATE_OF_BIRTH" in item["rule_id"] for item in anomalies)


def test_bureau_apr_month_and_branch_id_are_not_compared_to_loan_data() -> None:
    trusted = {
        "apr": "29.82",
        "branch": "JHALAWAR",
        "people": {"primary": {"applicant_name": "Peeru Lal"}},
    }
    anomalies = run_consistency_checks(
        [page(1, "CIBIL Report", "primary", applicant_name="Peeru Lal", apr="MAR", branch="ID")],
        trusted,
    )
    assert not any("APR" in item["rule_id"] or "BRANCH" in item["rule_id"] for item in anomalies)
