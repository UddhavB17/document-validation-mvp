import json

from services.review.repository import _comparison_evidence_page_numbers


def test_review_evidence_candidates_skip_pages_without_expected_fields() -> None:
    pages = [
        {"page_number": 1, "extracted_fields": json.dumps({"loan_amount": "500000"})},
        {
            "page_number": 2,
            "extracted_fields": json.dumps({"document_title": "Terms and conditions"}),
        },
        {
            "page_number": 3,
            "extracted_fields": json.dumps(
                {"person_records": [{"applicant_name": "Ramesh Kumar"}]}
            ),
        },
    ]
    ground_truth = {
        "raw_json": json.dumps(
            {
                "loan_amount": "500000",
                "people": {"primary": {"applicant_name": "Ramesh Kumar"}},
            }
        )
    }

    assert _comparison_evidence_page_numbers(pages, ground_truth) == [1, 3]


def test_review_evidence_candidates_return_empty_without_ground_truth() -> None:
    pages = [{"page_number": 1, "extracted_fields": json.dumps({"loan_amount": "500000"})}]

    assert _comparison_evidence_page_numbers(pages, None) == []


def test_legacy_legal_and_apr_evidence_can_be_recovered_from_text() -> None:
    pages = [
        {"page_number": 1, "document_type": "Title Deed Memorandum"},
        {"page_number": 2, "document_type": "KFS"},
        {"page_number": 3, "document_type": "Unknown"},
    ]
    ground_truth = {
        "raw_json": json.dumps({"apr": 24.54, "people": {"primary": {"date_of_birth": "1976-01-01"}}})
    }

    assert _comparison_evidence_page_numbers(
        [{**page, "extracted_fields": "{}"} for page in pages], ground_truth
    ) == [1, 2]
