from services.validation_gates import (
    compatible_field_for_document,
    field_reliable_for_validation,
    has_bank_statement_anchor,
)


def test_statement_period_fields_alone_are_not_a_bank_statement_anchor() -> None:
    assert not has_bank_statement_anchor(
        "Bank Statement",
        {
            "statement_period_start": "2026-07-31",
            "statement_period_end": "2026-07-31",
        },
    )


def test_account_identifier_can_anchor_a_bank_statement() -> None:
    assert has_bank_statement_anchor(
        "Bank Statement Account No. 123456789012",
        {},
    )


def test_transaction_column_signature_can_anchor_a_bank_statement() -> None:
    assert has_bank_statement_anchor(
        "Account Statement\nDate Narration Debit Credit Balance",
        {},
    )


def test_lender_statement_with_dr_cr_columns_is_a_bank_statement_anchor() -> None:
    assert has_bank_statement_anchor(
        "Customer's Statement of Account\n"
        "Name\nTIKARAM MEENA\nLoan Account No.\n221205302480415\n"
        "Date Particulars Dr. Cr. Balance",
        {"account_holder_name": "TIKARAM MEENA"},
    )


def test_repayment_schedule_continuation_is_not_a_bank_statement() -> None:
    assert not has_bank_statement_anchor(
        "Due Date Principal Interest Instalment Balance\n31/08/2026 2500 750 3250 447500",
        {
            "statement_period_start": "2026-08-31",
            "statement_period_end": "2027-08-31",
        },
    )


def test_disbursal_continuation_is_not_a_bank_statement() -> None:
    assert not has_bank_statement_anchor(
        "Foreclosure Letter or Statement of Account submitted by the customer at the time of disbursement",
        {
            "statement_period_start": "2026-07-31",
            "statement_period_end": "2026-07-31",
        },
    )


def test_insurer_local_application_id_is_not_loan_validation_evidence() -> None:
    page = {
        "ocr_text": (
            "Care Health Insurance Limited IRDAI Registration No. 148\n"
            "Group Care 360 Application Form\n"
            "Proposer Nominee Policy Sum Insured Premium\n"
            "Application No: 0030705"
        ),
        "extracted_fields": {"application_number": "0030705"},
    }

    assert not compatible_field_for_document("Insurance Form", "application_number", page)


def test_insurance_form_keeps_explicit_loan_account_id_as_validation_evidence() -> None:
    page = {
        "ocr_text": (
            "Care Health Insurance Limited IRDAI Registration No. 148\n"
            "Group Care 360 Application Form\n"
            "Proposer Nominee Policy Sum Insured Premium\n"
            "Loan Account No: 5000030765\nApplication No: 0030705"
        ),
        "extracted_fields": {"application_number": "5000030765"},
    }

    assert compatible_field_for_document("Insurance Form", "application_number", page)


def test_cached_page_counter_is_not_reliable_address_evidence() -> None:
    page = {
        "document_type": "Application Form",
        "classification_confidence": 0.99,
        "ocr_text": "PERMANENT ADDRESS\nPage 2 of 128",
        "extracted_fields": {"permanent_address": "Page 2 of 128"},
    }

    assert not field_reliable_for_validation(
        page,
        "permanent_address",
        "Page 2 of 128",
        expected_document_type="Application Form",
    )
