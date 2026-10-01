"""Review must use saved extraction, never expected data or stale exports."""

import json
from copy import deepcopy

import pytest

from services.review.comparison_matrix import build_comparison_matrix_and_relationships


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
