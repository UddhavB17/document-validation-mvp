from services.repayment_schedule import (
    collect_repayment_schedules,
    extract_repayment_summary,
    parse_repayment_schedule_rows,
    validate_repayment_schedules,
)


def _page(number: int, text: str, document_type: str = "Unknown") -> dict:
    return {
        "page_number": number,
        "document_type": document_type,
        "page_type": "digital",
        "classification_confidence": 0.99,
        "ocr_text": text,
        "extracted_fields": {},
    }


def test_schedule_continuation_is_detected_without_document_classification() -> None:
    rows = parse_repayment_schedule_rows(
        "19 399921.37 10266.00 3267.38 6998.62 396653.99\n"
        "20 396653.99 10266.00 3324.56 6941.44 393329.43"
    )

    assert [row["installment_number"] for row in rows] == [19, 20]
    assert all(row["component_valid"] and row["balance_valid"] for row in rows)


def test_schedule_rows_accept_native_script_digits() -> None:
    rows = parse_repayment_schedule_rows(
        "१ १०००.०० ५५०.०० ५००.०० ५०.०० ५००.००\n"
        "२ ५००.०० ५२५.०० ५००.०० २५.०० ०.००"
    )

    assert [row["installment_number"] for row in rows] == [1, 2]


def test_interest_only_pre_emi_is_not_counted_as_an_amortizing_installment() -> None:
    pages = [
        _page(
            1,
            "Repayment Schedule EMI (In Rs.) Principal Interest Closing Balance\n"
            "1 100000.00 1000.00 0.00 1000.00 100000.00\n"
            "2 100000.00 51000.00 50000.00 1000.00 50000.00",
            "Loan Agreement",
        ),
        _page(2, "3 50000.00 50500.00 50000.00 500.00 0.00", "Bank Statement"),
    ]

    anomalies = validate_repayment_schedules(
        pages,
        {"loan_amount": 100000, "emi": 51000, "installment_count": 2},
    )

    assert not any(
        item["rule_id"] == "REPAYMENT_SCHEDULE_INSTALLMENT_COUNT_MISMATCH"
        for item in anomalies
    )


def test_schedule_totals_are_not_part_of_repayment_validation() -> None:
    summary = (
        "Illustration for computation of APR for Retail and MSME loans\n"
        "1. Sanctioned Loan Amount (in Rupees)\n100000.00\n"
        "2. Loan Term (in months)\n2\nMonthly 51000.00 & 2\n"
        "5. Total interest amount to be charged during the entire tenure\n2000.00\n"
        "6. Fee/ Charges payable\n100.00\n"
        "8. Total amount to be paid by the borrower (sum of 1 and 5)\n150000.00\n"
    )
    pages = [
        _page(1, summary, "KFS"),
        _page(
            2,
            "Repayment Schedule EMI (In Rs.) Principal Interest Closing Balance\n"
            "1 100000.00 51000.00 50000.00 1000.00 50000.00\n"
            "2 50000.00 51000.00 50000.00 1000.00 0.00",
            "Loan Agreement",
        ),
    ]

    anomalies = validate_repayment_schedules(
        pages,
        {"loan_amount": 100000, "emi": 51000, "installment_count": 2},
    )
    rules = {item["rule_id"] for item in anomalies}

    assert extract_repayment_summary(summary)["total_repayment"] == 150000
    assert rules == set()


def test_generic_repayment_schedule_reference_does_not_authorize_summary() -> None:
    text = (
        "The borrower shall repay according to the repayment schedule attached.\n"
        "Total repayment 150000.00"
    )

    assert extract_repayment_summary(text) == {}


def test_blank_facility_amount_does_not_swallow_rate_of_interest() -> None:
    text = (
        "Key Facts Statement\n"
        "Amount of Facility\n"
        "Rate of Interest (%)\n"
        "21.00\n"
        "Total amount to be paid by the borrower\n"
        "150000.00"
    )

    summary = extract_repayment_summary(text)

    assert "loan_amount" not in summary
    assert summary["roi"] == 21
    assert summary["total_repayment"] == 150000


def test_kfs_boilerplate_clause_number_is_not_repayment_roi() -> None:
    text = (
        "5.\nIn case of collaborative lending, details may be furnished:\n"
        "Blended rate of interest\n"
        "6.\nIn case of digital loans, specific disclosures may be furnished.\n"
        "The IRR and Repayment Schedule specified in this Key Facts Statement (KFS) "
        "are subject to change."
    )

    assert extract_repayment_summary(text) == {}


def test_row_arithmetic_and_balance_are_not_business_validation_rules() -> None:
    pages = [
        _page(
            4,
            "Repayment Schedule EMI (In Rs.) Principal Interest Closing Balance\n"
            "1 100000.00 51000.00 49000.00 1000.00 49000.00\n"
            "2 49000.00 50000.00 49000.00 1000.00 0.00",
            "Facility Agreement",
        )
    ]

    anomalies = validate_repayment_schedules(pages, {"loan_amount": 100000, "emi": 50000})
    rules = [item["rule_id"] for item in anomalies]

    assert "REPAYMENT_SCHEDULE_EMI_COMPONENT_MISMATCH" not in rules
    assert "REPAYMENT_SCHEDULE_BALANCE_MISMATCH" not in rules


def test_only_recurring_emi_and_installment_count_are_compared() -> None:
    pages = [
        _page(
            1,
            "Repayment Schedule EMI (In Rs.) Principal Interest Closing Balance\n"
            "1 1000.00 550.00 500.00 50.00 500.00\n"
            "2 500.00 525.00 500.00 25.00 0.00",
            "Repayment Schedule",
        )
    ]

    anomalies = validate_repayment_schedules(
        pages,
        {"emi": 600, "installment_count": 3, "total_repayment": 999999},
    )
    rules = {item["rule_id"] for item in anomalies}

    assert rules == {
        "REPAYMENT_SCHEDULE_EMI_MISMATCH",
        "REPAYMENT_SCHEDULE_INSTALLMENT_COUNT_MISMATCH",
    }


def test_identical_schedule_copies_are_collapsed() -> None:
    text = (
        "Repayment Schedule EMI (In Rs.) Principal Interest Closing Balance\n"
        "1 1000.00 550.00 500.00 50.00 500.00\n"
        "2 500.00 525.00 500.00 25.00 0.00"
    )

    schedules = collect_repayment_schedules([_page(1, text), _page(20, text)])

    assert len(schedules) == 1
