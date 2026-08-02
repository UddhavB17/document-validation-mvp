from services.pipeline import (
    _assign_sequential_document_type,
    _infer_document_type_from_filename,
    _smooth_page_classifications,
)


def _apply_sequence(raw_results: list[dict], texts: list[str] | None = None) -> list[dict]:
    current_type = "Unknown"
    current_confidence = 0.0
    current_detected_page = None
    assigned = []
    texts = texts or [""] * len(raw_results)

    for index, raw in enumerate(raw_results, start=1):
        result = _assign_sequential_document_type(
            page_number=index,
            text=texts[index - 1],
            classification=raw,
            current_type=current_type,
            current_confidence=current_confidence,
            current_detected_page=current_detected_page,
        )
        assigned.append(result)
        if result["detection_method"] == "detected":
            current_type = result["document_type"]
            current_confidence = result["confidence"]
            current_detected_page = index

    return assigned


def test_continuation_pages_inherit_from_first_detected_page() -> None:
    assigned = _apply_sequence(
        [
            {"document_type": "Technical Report", "confidence": 0.95},
            {"document_type": "None", "confidence": 0.0},
            {"document_type": "None", "confidence": 0.0},
            {"document_type": "None", "confidence": 0.0},
            {"document_type": "None", "confidence": 0.0},
        ]
    )

    assert [page["document_type"] for page in assigned] == ["Technical Report"] * 5
    assert assigned[0]["detection_method"] == "detected"
    assert [page["detection_method"] for page in assigned[1:]] == ["inherited"] * 4
    assert [page["detected_page_number"] for page in assigned] == [1, 1, 1, 1, 1]


def test_high_confidence_type_change_starts_new_document_boundary() -> None:
    assigned = _apply_sequence(
        [
            {"document_type": "Technical Report", "confidence": 0.95},
            {"document_type": "None", "confidence": 0.0},
            {"document_type": "Aadhaar", "confidence": 0.91},
            {"document_type": "None", "confidence": 0.0},
        ]
    )

    assert [page["document_type"] for page in assigned] == [
        "Technical Report",
        "Technical Report",
        "Aadhaar",
        "Aadhaar",
    ]
    assert assigned[2]["detection_method"] == "detected"
    assert assigned[3]["detected_page_number"] == 3


def test_pan_never_inherits_into_unclassified_following_pages() -> None:
    assigned = _apply_sequence(
        [
            {"document_type": "PAN", "confidence": 0.95},
            {"document_type": "None", "confidence": 0.0},
            {"document_type": "None", "confidence": 0.0},
        ],
        texts=[
            "INCOME TAX DEPARTMENT Permanent Account Number ABCDE1234F",
            "Presentation Endorsement property boundary details",
            "Endorsement of Execution land registration details",
        ],
    )

    assert [page["document_type"] for page in assigned] == ["PAN", "Unknown", "Unknown"]
    assert assigned[1]["abstain_reason"] == "single-page-identity-document-does-not-inherit"


def test_smoothing_does_not_turn_unknown_page_into_identity_document() -> None:
    pages = [
        {"page_number": 1, "document_type": "PAN", "classification_confidence": 0.95, "extracted_fields": {}},
        {"page_number": 2, "document_type": "Unknown", "classification_confidence": 0.0, "ocr_text": "property deed", "extracted_fields": {}},
        {"page_number": 3, "document_type": "PAN", "classification_confidence": 0.95, "extracted_fields": {}},
    ]

    smoothed = _smooth_page_classifications(pages, application_id=None, total_pages=3)

    assert smoothed[1]["document_type"] == "Unknown"


def test_sequence_starting_unknown_does_not_inherit_until_first_detection() -> None:
    assigned = _apply_sequence(
        [
            {"document_type": "None", "confidence": 0.0},
            {"document_type": "None", "confidence": 0.0},
            {"document_type": "Bank Statement", "confidence": 0.9},
            {"document_type": "None", "confidence": 0.0},
        ]
    )

    assert [page["document_type"] for page in assigned] == [
        "Unknown",
        "Unknown",
        "Bank Statement",
        "Bank Statement",
    ]
    assert assigned[0]["detection_method"] == "unknown"
    assert assigned[1]["detection_method"] == "unknown"
    assert assigned[3]["detection_method"] == "inherited"


def test_fresh_page_devanagari_affidavit_does_not_inherit() -> None:
    assigned = _apply_sequence(
        [
            {"document_type": "Application Form", "confidence": 0.95},
            {"document_type": "None", "confidence": 0.0},
        ],
        texts=[
            "Loan application form",
            "यह शपथ पत्र प्रस्तुत है और NOTARY ATTESTED किया गया है",
        ],
    )

    assert assigned[1]["document_type"] == "Unknown"
    assert assigned[1]["detection_method"] == "unknown"
    assert assigned[1]["abstain_reason"] == "fresh-page-like-no-match"


def test_fresh_page_patta_does_not_inherit() -> None:
    assigned = _apply_sequence(
        [
            {"document_type": "PAN", "confidence": 0.95},
            {"document_type": "None", "confidence": 0.0},
        ],
        texts=[
            "Permanent Account Number ABCDE1234F",
            "राजस्थान पट्टा प्रपत्र 23-क ग्राम पंचायत भूमि विवरण",
        ],
    )

    assert assigned[1]["document_type"] == "Unknown"
    assert assigned[1]["detection_method"] == "unknown"
    assert assigned[1]["abstain_reason"] == "fresh-page-like-no-match"


def test_blank_continuation_still_inherits() -> None:
    assigned = _apply_sequence(
        [
            {"document_type": "Bank Statement", "confidence": 0.95},
            {"document_type": "None", "confidence": 0.0},
        ],
        texts=["Bank Statement Account Statement Debit Credit Balance", ""],
    )

    assert assigned[1]["document_type"] == "Bank Statement"
    assert assigned[1]["detection_method"] == "inherited"


def test_body_word_does_not_create_boundary_on_single_line_digital_page() -> None:
    body = "Continuation terms and repayment details " + ("x" * 500) + " report statement letter"
    assigned = _apply_sequence(
        [
            {"document_type": "KFS", "confidence": 1.0},
            {"document_type": "None", "confidence": 0.0},
        ],
        texts=["Key Fact Statement", body],
    )
    assert assigned[1]["document_type"] == "KFS"
    assert assigned[1]["detection_method"] == "inherited"


def test_mid_confidence_type_change_starts_new_document_boundary() -> None:
    assigned = _apply_sequence(
        [
            {"document_type": "Loan Agreement", "confidence": 0.95},
            {"document_type": "None", "confidence": 0.0},
            {"document_type": "Bank Statement", "confidence": 0.62},
            {"document_type": "None", "confidence": 0.0},
        ],
        texts=[
            "Facility Agreement Borrower Lender",
            "Article 19 Event of Default repayment schedule",
            "Brought Forward End Balance NEFT Debit Credit",
            "Opening Balance Closing Balance Transaction Date",
        ],
    )

    assert [page["document_type"] for page in assigned] == [
        "Loan Agreement",
        "Loan Agreement",
        "Bank Statement",
        "Bank Statement",
    ]
    assert assigned[2]["detection_method"] == "detected"
    assert assigned[3]["detection_method"] == "inherited"


def test_generic_header_words_do_not_break_agreement_inheritance() -> None:
    assigned = _apply_sequence(
        [
            {"document_type": "Loan Agreement", "confidence": 0.95},
            {"document_type": "None", "confidence": 0.0},
        ],
        texts=[
            "Facility Agreement Borrower Lender",
            "This form letter statement continues the repayment schedule and covenants",
        ],
    )

    assert assigned[1]["document_type"] == "Loan Agreement"
    assert assigned[1]["detection_method"] == "inherited"


def test_bank_statement_unknown_gap_is_sandwich_smoothed() -> None:
    pages = [
        {
            "page_number": 1,
            "document_type": "Bank Statement",
            "classification_confidence": 0.92,
            "extracted_fields": {},
        },
        {
            "page_number": 2,
            "document_type": "Unknown",
            "classification_confidence": 0.0,
            "ocr_text": "Debit Credit Balance NEFT Transaction",
            "extracted_fields": {},
        },
        {
            "page_number": 3,
            "document_type": "Bank Statement",
            "classification_confidence": 0.90,
            "extracted_fields": {},
        },
    ]

    smoothed = _smooth_page_classifications(pages, application_id=None, total_pages=3)
    assert smoothed[1]["document_type"] == "Bank Statement"


def test_generic_zip_folders_are_not_invented_as_document_types() -> None:
    assert _infer_document_type_from_filename("Loan/TASK/5.pdf") is None
    assert _infer_document_type_from_filename("LOAN/REPORT/combined.pdf") is None
    assert _infer_document_type_from_filename("Applicant/KYC/1781168594259.pdf") is None


def test_smoothed_unknown_page_marks_unanchored_identity_unreliable() -> None:
    pages = [
        {"page_number": 1, "document_type": "Application Form", "classification_confidence": 0.95, "extracted_fields": {}},
        {
            "page_number": 2,
            "document_type": "Unknown",
            "classification_confidence": 0.0,
            "ocr_text": "APPLICATION DETAILS\nApplicant Name\nRamesh Kumar\n",
            "extracted_fields": {"_classification": {"raw_document_type": "Unknown"}},
        },
        {"page_number": 3, "document_type": "Application Form", "classification_confidence": 0.95, "extracted_fields": {}},
    ]

    smoothed = _smooth_page_classifications(pages, application_id=None, total_pages=3)

    fields = smoothed[1]["extracted_fields"]
    assert smoothed[1]["document_type"] == "Application Form"
    assert fields["applicant_name"] == "Ramesh Kumar"
    assert fields["_identity_extraction_reliable"] is False


def test_evidentiary_filenames_have_safe_specific_fallbacks() -> None:
    assert _infer_document_type_from_filename("Loan/TASK/peeru spdc.pdf") == "PDC"
    assert _infer_document_type_from_filename("Loan/TASK/insurance Calu.pdf") == "Insurance Form"
    assert _infer_document_type_from_filename("Loan/TASK/Radha bai 6 month banking.pdf") == "Bank Statement"
    assert _infer_document_type_from_filename("LOAN/COLLATERAL/IMG-1.jpg") == "Property Image"
    assert _infer_document_type_from_filename("LOAN/COLLATERAL/peeru lal proprty paper.pdf") == "Property Document"
    assert _infer_document_type_from_filename("Loan/TASK/House Photo.pdf") == "House Photo"
    assert _infer_document_type_from_filename("Loan/TASK/Working Place Visit.pdf") == "Workplace Photo"
