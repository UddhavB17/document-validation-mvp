from services.pipeline import (
    _assign_sequential_document_type,
    _infer_document_type_from_filename,
    _refresh_page_from_cached_ocr,
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
        {
            "page_number": 1,
            "document_type": "PAN",
            "classification_confidence": 0.95,
            "extracted_fields": {},
        },
        {
            "page_number": 2,
            "document_type": "Unknown",
            "classification_confidence": 0.0,
            "ocr_text": "property deed",
            "extracted_fields": {},
        },
        {
            "page_number": 3,
            "document_type": "PAN",
            "classification_confidence": 0.95,
            "extracted_fields": {},
        },
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


def test_agreement_references_do_not_open_false_kfs_or_moa_documents() -> None:
    assigned = _apply_sequence(
        [
            {"document_type": "Facility Agreement", "confidence": 1.0},
            {"document_type": "KFS", "confidence": 1.0},
            {"document_type": "MOA AOA", "confidence": 1.0},
            {"document_type": "Loan Agreement", "confidence": 1.0},
        ],
        texts=[
            "FACILITY AGREEMENT Borrower Lender",
            "Event of Default: charges are listed in the KFS. Borrower shall repay the Lender. "
            * 8,
            "The Borrower represents that its Memorandum and Articles do not conflict with this Agreement. "
            * 8,
            "કલમ 7 ઉધારકર્તા લોનદાતા લોન કરાર ચુકવણીની શરતો",
        ],
    )

    assert [page["document_type"] for page in assigned] == ["Facility Agreement"] * 4
    assert [page["detection_method"] for page in assigned[1:]] == ["inherited"] * 3


def test_true_kfs_heading_breaks_open_agreement_run() -> None:
    assigned = _apply_sequence(
        [
            {"document_type": "Facility Agreement", "confidence": 1.0},
            {"document_type": "KFS", "confidence": 1.0},
        ],
        texts=[
            "FACILITY AGREEMENT Borrower Lender",
            "KEY FACT STATEMENT\nLoan amount APR tenure and instalment details",
        ],
    )

    assert assigned[1]["document_type"] == "KFS"
    assert assigned[1]["detection_method"] == "detected"


def test_embedded_kfs_heading_breaks_agreement_and_keeps_kfs_tables_together() -> None:
    assigned = _apply_sequence(
        [
            {"document_type": "Loan Agreement", "confidence": 0.82},
            {"document_type": "Loan Agreement", "confidence": 1.0},
            {"document_type": "Property Insurance Form", "confidence": 1.0},
            {"document_type": "Loan Agreement", "confidence": 1.0},
            {"document_type": "Loan Agreement", "confidence": 0.85},
            {"document_type": "Sanction Letter", "confidence": 1.0},
        ],
        texts=[
            (
                "Borrower consent and information sharing clauses. "
                * 20
                + "\nKEY FACT STATEMENT (KFS)\nPART - 1 (Interest Rate & Fees/Charges)\n"
                "Loan Proposal/Ac No. GJ000030765\nSanctioned loan Amount (in Rs.) 450000.00"
            ),
            (
                "Type Of Loan\nLoan Terms (Months) 84\nInstallments Details\n"
                "Frequency Of EPIs Monthly\nInterest rate 21.00 Fixed"
            ),
            (
                "Annual Percentage Rate (APR) 24.27\nDetails of Contingent Charges\n"
                "Foreclosure Charges\nLong Tenor Fee"
            ),
            (
                "Part 2 (Other qualitative information)\n"
                "Clause of Loan agreement relating to recovery agents"
            ),
            (
                "The IRR and Repayment Schedule specified in this Key Facts Statement (KFS) "
                "may change with the actual disbursement date."
            ),
            "SANCTION LETTER\nApplicant Name SUTHAR ANUPKUMAR\nSanction Amount 450000",
        ],
    )

    assert assigned[0]["document_type"] == "KFS"
    assert [page["document_type"] for page in assigned[:5]] == ["KFS"] * 5
    assert assigned[5]["document_type"] == "Sanction Letter"
    assert assigned[5]["detection_method"] == "detected"


def test_agreement_sentence_referencing_sanction_letter_is_not_a_new_heading() -> None:
    assigned = _apply_sequence(
        [
            {"document_type": "Facility Agreement", "confidence": 1.0},
            {"document_type": "KFS", "confidence": 1.0},
        ],
        texts=[
            "FACILITY AGREEMENT Borrower Lender",
            (
                "Any other terms not specifically covered herein but stipulated in the "
                "Sanction Letter should be complied with. The Borrower shall pay charges "
                "as per the schedule of charges/KFS. The Lender may require documents. "
            )
            * 6,
        ],
    )

    assert assigned[1]["document_type"] == "Facility Agreement"
    assert assigned[1]["detection_method"] == "inherited"


def test_bureau_appendix_account_table_stays_with_crif_report() -> None:
    assigned = _apply_sequence(
        [
            {"document_type": "CRIF Report", "confidence": 1.0},
            {"document_type": "Bank Statement", "confidence": 1.0},
        ],
        texts=[
            "CRIF High Mark Credit Information Report Credit Score",
            "Appendix Account Information Payment History Overdue Asset Classification",
        ],
    )

    assert assigned[1]["document_type"] == "CRIF Report"
    assert assigned[1]["detection_method"] == "inherited"


def test_bureau_appendix_detected_as_crif_still_inherits_open_report() -> None:
    assigned = _apply_sequence(
        [
            {"document_type": "CRIF Report", "confidence": 1.0},
            {"document_type": "CRIF Report", "confidence": 1.0},
        ],
        texts=[
            "CRIF High Mark Credit Information Report Consumer Name Mosmee Meena Credit Score",
            "Account Information Payment History Overdue High Mark Credit Member Asset Classification",
        ],
    )

    assert assigned[1]["document_type"] == "CRIF Report"
    assert assigned[1]["detection_method"] == "inherited"
    assert assigned[1]["detected_page_number"] == 1


def test_statement_nach_transactions_do_not_start_a_nach_document() -> None:
    assigned = _apply_sequence(
        [
            {"document_type": "Bank Statement", "confidence": 1.0},
            {"document_type": "NACH Form", "confidence": 1.0},
        ],
        texts=[
            "Customer's Statement of Account Date Particulars Debit Credit Balance",
            (
                "Amount Received Mode - NACH Instrument NO-NACH48041510022026 "
                "Loan Allocation Amount 10195 Txn Date 2026-02-10 "
                "Value Date 2026-02-10 Receipt No RV1"
            ),
        ],
    )

    assert assigned[1]["document_type"] == "Bank Statement"
    assert assigned[1]["inheritance_warning"] == "statement-ledger-continuation"


def test_disbursement_request_continuation_is_not_bank_statement() -> None:
    assigned = _apply_sequence(
        [
            {"document_type": "Disbursement Request", "confidence": 1.0},
            {"document_type": "Bank Statement", "confidence": 1.0},
        ],
        texts=[
            "Request For Disbursal\nLoan No GJ000030765",
            "In case of Balance Transfer use the Foreclosure Letter or Statement of Account. Yours faithfully.",
        ],
    )

    assert assigned[1]["document_type"] == "Disbursement Request"
    assert assigned[1]["detection_method"] == "inherited"


def test_sanction_conditions_do_not_split_on_property_agreement_or_stamp_references() -> None:
    assigned = _apply_sequence(
        [
            {"document_type": "Sanction Letter", "confidence": 1.0},
            {"document_type": "Property Document", "confidence": 1.0},
            {"document_type": "Loan Agreement", "confidence": 1.0},
            {"document_type": "Stamp Duty", "confidence": 1.0},
            {"document_type": "Facility Agreement", "confidence": 1.0},
        ],
        texts=[
            "SANCTION LETTER\nSanctioned amount loan tenure and interest rate",
            "Credit verification before disbursement. Property security documents and sanction conditions. "
            * 6,
            "The offer and terms and conditions remain valid until loan disbursement. Sanction conditions apply. "
            * 6,
            "મંજૂરી પત્રની શરતો લોન વિતરણ વ્યાજ દર અને સ્ટેમ્પ ડ્યુટી અંગે લાગુ પડશે. " * 8,
            "FACILITY AGREEMENT\nThis agreement is between the Borrower and the Lender",
        ],
    )

    assert [page["document_type"] for page in assigned[:4]] == ["Sanction Letter"] * 4
    assert assigned[4]["document_type"] == "Facility Agreement"
    assert assigned[4]["detection_method"] == "detected"


def test_self_attested_sanction_condition_is_not_a_new_document_boundary() -> None:
    assigned = _apply_sequence(
        [
            {"document_type": "Sanction Letter", "confidence": 1.0},
            {"document_type": "Property Document", "confidence": 1.0},
            {"document_type": "Stamp Duty", "confidence": 1.0},
            {"document_type": "Facility Agreement", "confidence": 1.0},
        ],
        texts=[
            "SANCTION LETTER\nSanctioned amount loan tenure and interest rate",
            (
                "Credit Verification: Disbursement is subject to satisfactory credit verification.\n"
                "Self-Attestation: All documents must be self-attested by the applicant.\n"
                "Disbursement Conditions: loan and security documents must satisfy the lender. "
            )
            * 6,
            (
                "Security for Loan: the property secures the loan. The borrower must provide "
                "documents before disbursement under these sanction conditions. "
            )
            * 7,
            "FACILITY AGREEMENT\nThis agreement is between the Borrower and the Lender",
        ],
    )

    assert [page["document_type"] for page in assigned[:3]] == ["Sanction Letter"] * 3
    assert assigned[3]["document_type"] == "Facility Agreement"
    assert assigned[3]["detection_method"] == "detected"


def test_real_sale_deed_heading_breaks_open_sanction_run() -> None:
    assigned = _apply_sequence(
        [
            {"document_type": "Sanction Letter", "confidence": 1.0},
            {"document_type": "Property Document", "confidence": 1.0},
        ],
        texts=[
            "SANCTION LETTER\nSanctioned amount and loan tenure",
            "SALE DEED\nRegistered property survey number and plot boundaries",
        ],
    )

    assert assigned[1]["document_type"] == "Property Document"
    assert assigned[1]["detection_method"] == "detected"


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


def test_smoothing_does_not_cross_zip_source_boundaries() -> None:
    pages = [
        {
            "page_number": 1,
            "document_type": "Bank Statement",
            "classification_confidence": 0.92,
            "source_document_id": "file-a",
            "extracted_fields": {},
        },
        {
            "page_number": 2,
            "document_type": "Unknown",
            "classification_confidence": 0.0,
            "source_document_id": "file-b",
            "ocr_text": "Debit Credit Balance Transaction",
            "extracted_fields": {},
        },
        {
            "page_number": 3,
            "document_type": "Bank Statement",
            "classification_confidence": 0.92,
            "source_document_id": "file-c",
            "extracted_fields": {},
        },
    ]

    smoothed = _smooth_page_classifications(pages, application_id=None, total_pages=3)

    assert smoothed[1]["document_type"] == "Unknown"


def test_generic_zip_folders_are_not_invented_as_document_types() -> None:
    assert _infer_document_type_from_filename("Loan/TASK/5.pdf") is None
    assert _infer_document_type_from_filename("LOAN/REPORT/combined.pdf") is None
    assert _infer_document_type_from_filename("Applicant/KYC/1781168594259.pdf") is None


def test_archive_root_folder_keywords_do_not_leak_into_every_member() -> None:
    # A shared ZIP root ("Quality_Checker_Documents") once matched the bare
    # "check" keyword and stamped "Cheque" onto all 175 unknown pages of a run.
    root = "26000_Quality_Checker_Documents"
    assert (
        _infer_document_type_from_filename(f"{root}/LOAN/TASK/Batti lal jambandi.pdf") != "Cheque"
    )
    assert (
        _infer_document_type_from_filename(f"{root}/LOAN/TASK/Technical Valuation Report (8).pdf")
        != "Cheque"
    )
    assert (
        _infer_document_type_from_filename(f"{root}/Co-Applicant/KYC/8955707373_aadhaar.pdf")
        == "Aadhaar"
    )
    assert (
        _infer_document_type_from_filename(f"{root}/Co-Applicant/KYC/1782724446316.jpeg")
        == "KYC Card Photo"
    )


def test_short_filename_keywords_require_word_boundaries() -> None:
    assert _infer_document_type_from_filename("Loan/TASK/KYC checklist.pdf") != "Cheque"
    assert _infer_document_type_from_filename("Loan/TASK/cancelled cheque peeru.pdf") == "Cheque"
    assert _infer_document_type_from_filename("Loan/TASK/CHQ scan.pdf") == "Cheque"
    assert _infer_document_type_from_filename("Loan/TASK/company profile.pdf") != "PAN Card"
    assert _infer_document_type_from_filename("Loan/KYC/pan card peeru.pdf") == "PAN Card"
    assert _infer_document_type_from_filename("Loan/TASK/handle bracket.pdf") != "Driving License"


def test_smoothed_unknown_page_marks_unanchored_identity_unreliable() -> None:
    pages = [
        {
            "page_number": 1,
            "document_type": "Application Form",
            "classification_confidence": 0.95,
            "extracted_fields": {},
        },
        {
            "page_number": 2,
            "document_type": "Unknown",
            "classification_confidence": 0.0,
            "ocr_text": "APPLICATION DETAILS\nApplicant Name\nRamesh Kumar\n",
            "extracted_fields": {"_classification": {"raw_document_type": "Unknown"}},
        },
        {
            "page_number": 3,
            "document_type": "Application Form",
            "classification_confidence": 0.95,
            "extracted_fields": {},
        },
    ]

    smoothed = _smooth_page_classifications(pages, application_id=None, total_pages=3)

    fields = smoothed[1]["extracted_fields"]
    assert smoothed[1]["document_type"] == "Application Form"
    assert fields["applicant_name"] == "Ramesh Kumar"
    assert fields["_identity_extraction_reliable"] is False


def test_evidentiary_filenames_have_safe_specific_fallbacks() -> None:
    assert _infer_document_type_from_filename("Loan/TASK/peeru spdc.pdf") == "PDC"
    assert _infer_document_type_from_filename("Loan/TASK/insurance Calu.pdf") == "Insurance Form"
    assert (
        _infer_document_type_from_filename("Loan/TASK/Radha bai 6 month banking.pdf")
        == "Bank Statement"
    )
    assert _infer_document_type_from_filename("LOAN/COLLATERAL/IMG-1.jpg") == "Property Image"
    assert (
        _infer_document_type_from_filename("LOAN/COLLATERAL/peeru lal proprty paper.pdf")
        == "Property Document"
    )
    assert _infer_document_type_from_filename("Loan/TASK/House Photo.pdf") == "House Photo"
    assert (
        _infer_document_type_from_filename("Loan/TASK/Working Place Visit.pdf") == "Workplace Photo"
    )


def test_cached_spdc_filename_overrides_bank_statement_content_classification() -> None:
    refreshed = _refresh_page_from_cached_ocr(
        {
            "page_number": 59,
            "page_type": "scanned",
            "ocr_text": "Bank account details A/c No. 0071000100264386 IFSC PUNB0007100",
            "ocr_confidence": 0.92,
            "document_type": "Bank Statement",
            "classification_confidence": 0.92,
            "extracted_fields": {"account_number": "0071000100264386"},
        },
        current_type="Unknown",
        current_confidence=0.0,
        current_detected_page=None,
        source_documents=[
            {
                "source_document_id": "file-0018",
                "original_filename": "LOAN/TASK/peeru spdc.pdf",
                "internal_page_start": 59,
                "internal_page_end": 60,
            }
        ],
    )

    assert refreshed["document_type"] == "PDC"
    assert refreshed["detection_method"] == "filename_override"
    assert refreshed["classification_confidence"] == 0.95


def test_unknown_filename_prose_does_not_invent_document_types() -> None:
    assert _infer_document_type_from_filename("Loan/TASK/customer approval.pdf") is None
    assert _infer_document_type_from_filename("Applicant/INCOME/TimePhoto_20260724.jpg") is None


def test_generic_kyc_photo_does_not_override_intrinsic_card_type() -> None:
    from services.pipeline import _source_filename_override_allowed

    assert _source_filename_override_allowed("KYC Card Photo", "PAN Card") is False
    assert _source_filename_override_allowed("KYC Card Photo", "Aadhaar") is False
    assert _source_filename_override_allowed("KYC Card Photo", "Unknown") is True


def test_guarantee_clauses_do_not_become_a_loan_agreement() -> None:
    assigned = _apply_sequence(
        [
            {"document_type": "Guarantee Deed", "confidence": 1.0},
            {"document_type": "Loan Agreement", "confidence": 1.0},
            {"document_type": "Loan Agreement", "confidence": 0.9},
        ],
        texts=[
            "DEED OF GUARANTEE\nExecuted by the Guarantor",
            "NOW THIS DEED OF GUARANTEE WITNESSETH. The Guarantor shall ensure repayment by the Borrower.",
            "This Guarantee remains effective under the Loan Agreement and binds the Guarantor.",
        ],
    )

    assert [page["document_type"] for page in assigned] == ["Guarantee Deed"] * 3
    assert assigned[1]["inheritance_warning"] == "guarantee-deed-run-context"


def test_application_form_declaration_does_not_become_a_loan_agreement() -> None:
    assigned = _apply_sequence(
        [
            {"document_type": "Application Form", "confidence": 1.0},
            {"document_type": "Loan Agreement", "confidence": 0.95},
            {"document_type": "Loan Agreement", "confidence": 0.9},
        ],
        texts=[
            "LOAN APPLICATION FORM\nApplicant details",
            "Co-Applicant Personal Details\nCurrent Resi. Address\nDate of Birth",
            "Declaration: I/We agree that this application for loan may be accepted by the Company.",
        ],
    )

    assert [page["document_type"] for page in assigned] == ["Application Form"] * 3
    assert assigned[1]["inheritance_warning"] == "application-form-run-context"


def test_application_continuation_guard_does_not_hide_unrelated_strong_document() -> None:
    assigned = _apply_sequence(
        [
            {"document_type": "Application Form", "confidence": 1.0},
            {"document_type": "Utility Bill", "confidence": 1.0},
        ],
        texts=[
            "LOAN APPLICATION FORM\nApplicant details",
            "ELECTRICITY BILL\nConsumer Address\nBilling Month July 2026",
        ],
    )

    assert assigned[1]["document_type"] == "Utility Bill"
    assert assigned[1]["detection_method"] == "detected"


def test_guarantee_continuation_guard_does_not_hide_legal_report() -> None:
    assigned = _apply_sequence(
        [
            {"document_type": "Guarantee Deed", "confidence": 1.0},
            {"document_type": "Legal Clearance Report", "confidence": 1.0},
        ],
        texts=[
            "DEED OF GUARANTEE\nExecuted by the Guarantor",
            "LEGAL SCRUTINY REPORT\nThe proposed guarantee and title are legally clear.",
        ],
    )

    assert assigned[1]["document_type"] == "Legal Clearance Report"


def test_explicit_facility_title_breaks_open_loan_agreement_run() -> None:
    assigned = _apply_sequence(
        [
            {"document_type": "Loan Agreement", "confidence": 1.0},
            {"document_type": "Facility Agreement", "confidence": 1.0},
        ],
        texts=[
            "LOAN AGREEMENT\nBorrower and Lender",
            "FACILITY AGREEMENT\nThis Facility Agreement is made between the parties.",
        ],
    )

    assert [page["document_type"] for page in assigned] == [
        "Loan Agreement",
        "Facility Agreement",
    ]
    assert assigned[1]["detection_method"] == "detected"


def test_agreement_body_affidavit_reference_does_not_switch_agreement_kind() -> None:
    assigned = _apply_sequence(
        [
            {"document_type": "Facility Agreement", "confidence": 1.0},
            {"document_type": "Loan Agreement", "confidence": 1.0},
        ],
        texts=[
            "FACILITY AGREEMENT\nThis agreement is made between the parties.",
            "10. Allow the Lender to conduct due diligence and obtain affidavits from the Borrower.",
        ],
    )

    assert [page["document_type"] for page in assigned] == ["Facility Agreement"] * 2
    assert assigned[1]["inheritance_warning"] == "agreement-run-context"


def test_agreement_body_misclassified_as_affidavit_does_not_split_facility_run() -> None:
    assigned = _apply_sequence(
        [
            {"document_type": "Facility Agreement", "confidence": 1.0},
            {"document_type": "Affidavit", "confidence": 1.0},
            {"document_type": "Loan Agreement", "confidence": 1.0},
        ],
        texts=[
            "FACILITY AGREEMENT\nThis agreement is made between Borrower and Lender.",
            (
                "11. Submit to the Lender a duly attested affidavit confirming the Borrower's "
                "name. The Borrower and Guarantor shall comply with this Agreement and repay "
                "the Facility. " * 5
            ),
            "The Borrower shall provide statements and comply with covenants under this Agreement. "
            * 6,
        ],
    )

    assert [page["document_type"] for page in assigned] == ["Facility Agreement"] * 3
