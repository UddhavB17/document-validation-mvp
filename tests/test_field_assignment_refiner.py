from services.field_assignment_refiner import _parse_toon_object, refine_field_assignments


def test_bank_table_labels_are_not_accepted_as_customer_values(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_LLM_FIELD_ASSIGNMENT", "false")
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


def test_table_column_headings_are_not_accepted_as_names(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_LLM_FIELD_ASSIGNMENT", "false")
    for value in ("Source", "Financer", "Issuing Authority", "Ration Card", "PHONE NO"):
        result = refine_field_assignments(
            document_type="Aadhaar",
            ocr_text=value,
            extracted_fields={"applicant_name": value},
        )
        assert result["applicant_name"] is None


def test_parse_field_assignment_accepts_json_and_fenced_json() -> None:
    raw = '{"fields": {"applicant_name": "Peeru Lal"}, "reason": "ok", "confidence": 0.9}'
    assert _parse_toon_object(raw)["fields"]["applicant_name"] == "Peeru Lal"
    fenced = "```json\n" + raw + "\n```"
    assert _parse_toon_object(fenced)["fields"]["applicant_name"] == "Peeru Lal"
    prose = "Here is the result:\n" + raw + "\nThanks"
    assert _parse_toon_object(prose)["fields"]["applicant_name"] == "Peeru Lal"


def test_parse_field_assignment_still_accepts_toon() -> None:
    toon = (
        "fields:\n"
        "  applicant_name: Peeru Lal\n"
        "reason: clear name\n"
        "confidence: 0.91\n"
    )
    assert _parse_toon_object(toon)["fields"]["applicant_name"] == "Peeru Lal"
