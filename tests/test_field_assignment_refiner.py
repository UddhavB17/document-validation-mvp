from services.field_assignment_refiner import refine_field_assignments


def test_bank_table_labels_are_not_accepted_as_customer_values() -> None:
    result = refine_field_assignments(
        document_type="Bank Statement",
        ocr_text="A/C HOLDER NAME A/C NUMEBER ACCOUNT TYPE खाता प्रकार",
        extracted_fields={
            "account_holder_name": "A/C NUMEBER",
            "account_type": "खाता प्रकार",
        },
    )
    assert result["account_holder_name"] is None
    assert result["account_type"] is None


def test_table_column_headings_are_not_accepted_as_names() -> None:
    for value in ("Source", "Financer", "Issuing Authority", "Ration Card", "PHONE NO"):
        result = refine_field_assignments(
            document_type="Aadhaar",
            ocr_text=value,
            extracted_fields={"applicant_name": value},
        )
        assert result["applicant_name"] is None
