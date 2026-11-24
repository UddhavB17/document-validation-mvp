"""Review must use saved extraction, never expected data or stale exports."""

import json
from copy import deepcopy

import pytest

from services.review.comparison_matrix import build_comparison_matrix_and_relationships
from services.reviewer import load_reviewer_comparison, save_reviewer_comparison


def page(number, document_type, fields, **extra):
    return {
        "page_number": number,
        "page_type": "digital",
        "document_type": document_type,
        "classification_confidence": 0.99,
        "extracted_fields": fields,
        **extra,
    }


def matrix(pages, *, people=None, **expected):
    data = {
        "ground_truth": {"raw_json": json.dumps({"people": people or {}, **expected})},
        "pages": pages,
        "anomalies": [],
        "application": dict(expected),
    }
    before = deepcopy(data)
    result = build_comparison_matrix_and_relationships(
        1, data, ocr_data={"combined_extracted_fields": expected}
    )["comparison_matrix"]
    assert data == before
    return result


def test_saved_identity_fields_work_without_export_and_keep_people_separate():
    people = {
        "primary": {
            "role": "primary",
            "applicant_name": "Arjun Sharma",
            "pan_number": "ABCDE1234F",
        },
        "coapp_1": {
            "role": "coapplicant",
            "applicant_name": "Meera Sharma",
            "pan_number": "FGHIJ5678K",
        },
    }
    result = matrix(
        [
            page(1, "PAN Card", {"applicant_name": "Arjun Sharma", "pan_number": "ABCDE1234F"}),
            page(2, "PAN Card", {"applicant_name": "Meera Sharma", "pan_number": "FGHIJ5678K"}),
        ],
        people=people,
    )
    for index, expected in enumerate(["ABCDE1234F", "FGHIJ5678K"]):
        field = next(
            row
            for row in result["applicants"][index]["fields"]
            if row["field_name"] == "pan_number"
        )
        assert field["extracted_value"] == expected
        assert field["source_pages"] == [index + 1]
        assert field["status"] == "match"


def test_expected_and_stale_export_values_never_count_as_extracted():
    result = matrix([], loan_amount="500000", branch="Delhi")
    assert all(
        row["extracted_value"] is None and row["source_pages"] == []
        for row in result["core_parameters"]
    )


@pytest.mark.parametrize("amount,status", [(500000, "match"), (600000, "mismatch")])
def test_core_fields_compare_actual_values_even_before_anomalies_exist(amount, status):
    result = matrix([page(9, "Sanction Letter", {"loan_amount": amount})], loan_amount="500000")
    field = result["core_parameters"][0]
    assert field["extracted_value"] == str(amount)
    assert field["source_pages"] == [9]
    assert field["status"] == status


def test_conflicting_sources_are_not_silently_marked_match():
    result = matrix(
        [
            page(1, "Sanction Letter", {"loan_amount": 500000}),
            page(2, "Loan Agreement", {"loan_amount": 700000}),
        ],
        loan_amount="500000",
    )
    assert result["core_parameters"][0]["status"] == "attention"
    assert result["core_parameters"][0]["source_pages"] == [1, 2]


def test_explicit_address_component_conflict_wins_over_matching_and_partial_sources():
    expected_address = "Flat 12B, Shanti Nagar, Jaipur 302001"
    result = matrix(
        [
            page(1, "Aadhaar", {"address": expected_address}),
            page(2, "Application Form", {"address": "Shanti Nagar"}),
            page(3, "Aadhaar", {"address": "Flat 13B, Shanti Nagar, Jaipur 302001"}),
        ],
        people={"primary": {"applicant_name": "Arjun Sharma", "address": expected_address}},
    )
    address = next(row for row in result["applicants"][0]["fields"] if row["field_name"] == "address")
    assert address["status"] == "mismatch"
    assert address["extracted_value"] == "Flat 13B, Shanti Nagar, Jaipur 302001"
    assert address["source_pages"] == [3, 1, 2]


def test_mixed_generic_address_sources_remain_attention():
    expected_address = "Shanti Nagar, Jaipur"
    result = matrix(
        [
            page(1, "Aadhaar", {"address": expected_address}),
            page(2, "Application Form", {"address": "Shanti Nagar, Delhi"}),
        ],
        people={"primary": {"applicant_name": "Arjun Sharma", "address": expected_address}},
    )
    address = next(row for row in result["applicants"][0]["fields"] if row["field_name"] == "address")
    assert address["status"] == "attention"


@pytest.mark.parametrize("attribution", [{"person_id": "primary"}, {"page_number": 1}])
def test_attributed_active_mismatch_overrides_partial_evidence(attribution):
    data = {
        "ground_truth": {
            "raw_json": json.dumps({"people": {"primary": {
                "applicant_name": "Arjun Sharma", "address": "Shanti Nagar, Jaipur"
            }}})
        },
        "pages": [page(1, "Application Form", {
            "applicant_name": "Arjun Sharma", "address": "Shanti Nagar, Jaipur"
        }), page(2, "Application Form", {
            "applicant_name": "Arjun Sharma", "address": "Shanti Nagar, Delhi"
        })],
        "anomalies": [{"rule_id": "TRUSTED_ADDRESS_MISMATCH", "severity": "HIGH", **attribution}],
        "application": {},
    }
    result = build_comparison_matrix_and_relationships(1, data)["comparison_matrix"]
    address = next(row for row in result["applicants"][0]["fields"] if row["field_name"] == "address")
    assert address["status"] == "mismatch"


def test_dismissed_attributed_mismatch_does_not_override_partial_evidence():
    data = {
        "ground_truth": {
            "raw_json": json.dumps({"people": {"primary": {
                "applicant_name": "Arjun Sharma", "address": "Shanti Nagar, Jaipur"
            }}})
        },
        "pages": [page(1, "Application Form", {
            "applicant_name": "Arjun Sharma", "address": "Shanti Nagar, Jaipur"
        }), page(2, "Application Form", {
            "applicant_name": "Arjun Sharma", "address": "Shanti Nagar, Delhi"
        })],
        "anomalies": [{
            "rule_id": "TRUSTED_ADDRESS_MISMATCH", "severity": "HIGH",
            "person_id": "primary", "status": "dismissed_by_llm",
        }],
        "application": {},
    }
    result = build_comparison_matrix_and_relationships(1, data)["comparison_matrix"]
    address = next(row for row in result["applicants"][0]["fields"] if row["field_name"] == "address")
    assert address["status"] == "attention"


def test_saved_kfs_text_supplies_apr_when_old_extraction_omitted_it():
    result = matrix(
        [page(2, "KFS", {}, ocr_text="Annual Percentage Rate (APR) (%)\nवार्षिक दर\n24.54%")],
        apr="24.54",
    )
    assert result["core_parameters"][0] == {
        "field_name": "apr",
        "label": "Annual Percentage Rate (APR)",
        "expected_value": "24.54",
        "extracted_value": "24.54",
        "status": "match",
        "source_pages": [2],
    }


def test_legal_dob_conflict_remains_visible_when_kyc_agrees_with_json():
    result = matrix(
        [
            page(1, "Aadhaar", {"applicant_name": "Meera Sharma", "date_of_birth": "1976-01-01"}),
            page(
                2, "Property Document", {}, page_type="scanned", ocr_confidence=0.97,
                ocr_text=(
                    "MEMORANDUM BY DEPOSIT OF TITLE DEEDS\n"
                    "Between\n"
                    "Smt. Meera Sharma W/o Sh. Ravi Sharma (DOB-01.01.1978) R/o Example Road\n"
                    '(Aadhar No. XXXX XXXX 1234) hereinafter referred as\n"THE FIRST PARTIES/OWNERS"'
                ),
            ),
        ],
        people={"primary": {
            "applicant_name": "Meera Sharma", "aadhaar_last4": "1234", "date_of_birth": "1976-01-01",
        }},
    )
    date = next(
        row for row in result["applicants"][0]["fields"] if row["field_name"] == "date_of_birth"
    )
    assert date["status"] == "mismatch"
    assert date["extracted_value"] == "1978-01-01"
    assert date["source_pages"] == [2, 1]


def test_unowned_person_field_is_not_assigned_to_primary():
    result = matrix(
        [page(1, "Aadhaar", {"gender": "FEMALE"})],
        people={
            "primary": {"applicant_name": "Arjun Sharma", "gender": "MALE"},
            "coapp_1": {"applicant_name": "Meera Sharma", "gender": "FEMALE"},
        },
    )
    assert all(
        row["extracted_value"] is None
        for person in result["applicants"]
        for row in person["fields"]
    )


def test_low_confidence_provenance_and_bank_branch_are_not_loan_evidence():
    result = matrix(
        [
            page(
                1,
                "Sanction Letter",
                {
                    "loan_amount": 500000,
                    "_field_provenance": {"loan_amount": {"field_confidence": 0.1}},
                },
            ),
            page(2, "Bank Statement", {"branch": "Delhi", "loan_amount": 500000}),
        ],
        loan_amount="500000",
        branch="Delhi",
    )
    assert all(row["extracted_value"] is None for row in result["core_parameters"])


def test_person_record_aliases_are_extracted_without_copying_expected():
    result = matrix(
        [
            page(
                1,
                "Application Form",
                {
                    "person_records": [
                        {
                            "applicant_name": "Arjun Sharma",
                            "pan_number": "ABCDE1234F",
                            "phone": "9876543210",
                            "pincode": "110001",
                        },
                        {
                            "applicant_name": "Meera Sharma",
                            "pan_number": "FGHIJ5678K",
                            "phone": "9876543211",
                            "pincode": "110002",
                        },
                    ]
                },
            )
        ],
        people={
            "primary": {
                "applicant_name": "Arjun Sharma",
                "pan_number": "ABCDE1234F",
                "phone_number": "9876543210",
                "pin_code": "110001",
            },
            "coapp_1": {
                "applicant_name": "Meera Sharma",
                "pan_number": "FGHIJ5678K",
                "phone_number": "9876543211",
                "pin_code": "110002",
            },
        },
    )
    for person in result["applicants"]:
        assert all(
            row["status"] == "match" and row["source_pages"] == [1] for row in person["fields"]
        )


def test_reviewer_comparison_round_trips_as_json(tmp_path, monkeypatch):
    import database.db as db
    from database.db import init_db

    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "reviewer-comparison.db")
    init_db()
    with db.get_connection() as connection:
        connection.execute("INSERT INTO applications (loan_id) VALUES (?)", ("CACHE-001",))
    expected_matrix = {"core_parameters": [{"field_name": "loan_amount"}], "applicants": []}
    expected_relationships = [{"source": 1, "target": 2}]

    save_reviewer_comparison(
        1, expected_matrix, expected_relationships, pipeline_job_id=42
    )
    assert load_reviewer_comparison(1) == {
        "pipeline_job_id": 42,
        "comparison_matrix": expected_matrix,
        "relationships": expected_relationships,
    }
    with db.get_connection() as connection:
        connection.execute(
            "UPDATE reviewer_comparisons SET comparison_matrix_json = ? WHERE application_id = ?",
            (json.dumps(expected_matrix), 1),
        )
    assert load_reviewer_comparison(1) is None


def test_permanent_comparison_uses_labelled_evidence_over_mailing_match():
    permanent = "Ward 01, Model Colony, Jaipur, Rajasthan 302001"
    mailing = "Ward 11, Model Colony, Jaipur, Rajasthan 302001"
    people = {"primary": {
        "applicant_name": "Arjun Sharma",
        "address": permanent,
        "communication_address": mailing,
    }}
    for pages, expected_status in [
        ([page(1, "Aadhaar", {"applicant_name": "Arjun Sharma", "address": mailing})], "attention"),
        ([page(2, "Application Form", {
            "applicant_name": "Arjun Sharma", "permanent_address": mailing,
        })], "mismatch"),
    ]:
        result = matrix(pages, people=people)
        address = next(row for row in result["applicants"][0]["fields"] if row["field_name"] == "address")
        assert address["status"] == expected_status
