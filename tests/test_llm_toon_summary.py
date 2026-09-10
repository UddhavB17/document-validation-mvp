from services.llm_service import build_default_summary, parse_llm_summary, summarize_exceptions


def test_parse_llm_summary_valid():
    toon_input = """
overall_summary: Verification completed with some minor exceptions.
final_recommendation: MANUAL REVIEW
page_summaries[2]:
  - page_number: 3
    document_type: Bank Statement
    summary_points[2]: Transaction history for John Doe,Covers April to June 2026
    problem_description: Name misspelling on account.
  - page_number: 5
    document_type: PAN Card
    summary_points[1]: Identity document for John Doe
    problem_description: PAN card number matches ground truth.
"""
    result = parse_llm_summary(toon_input)
    assert result is not None
    assert result["overall_summary"] == "Verification completed with some minor exceptions."
    assert result["final_recommendation"] == "MANUAL REVIEW"
    assert len(result["page_summaries"]) == 2
    assert result["page_summaries"][0]["page_number"] == 3
    assert result["page_summaries"][0]["document_type"] == "Bank Statement"
    assert result["page_summaries"][0]["summary_points"] == [
        "Transaction history for John Doe",
        "Covers April to June 2026",
    ]
    assert result["page_summaries"][0]["problem_description"] == "Name misspelling on account."


def test_parse_llm_summary_fenced():
    toon_input = """
```toon
overall_summary: Code block wrapped test.
final_recommendation: APPROVE

page_summaries[1]{page_number,document_type,summary_points,problem_description}:
  1,Cheque,["Cancelled cheque copy"],None
```
"""
    result = parse_llm_summary(toon_input)
    assert result is not None
    assert result["overall_summary"] == "Code block wrapped test."
    assert result["final_recommendation"] == "APPROVE"
    assert len(result["page_summaries"]) == 1


def test_parse_llm_summary_invalid():
    assert parse_llm_summary("") is None
    assert parse_llm_summary("this is just arbitrary text not toon format") is None


def test_build_default_summary():
    anomalies = [
        {
            "page_number": 2,
            "document_type": "PAN Card",
            "rule_id": "PAN_NUMBER_MISMATCH",
            "severity": "HIGH",
            "reason": "PAN number does not match ground truth.",
            "expected_value": "ABCDE1234F",
            "found_value": "TSTPA7002Z",
        }
    ]
    ground_truth = {"loan_id": "LAP-101", "applicant_name": "Ramesh Kumar"}
    result = build_default_summary(anomalies, ground_truth)

    assert result["overall_summary"] == "1 exception(s) require review: 1 high-severity"
    assert result["final_recommendation"] == "MANUAL REVIEW"
    assert len(result["page_summaries"]) == 1
    assert result["page_summaries"][0]["page_number"] == 2
    assert result["page_summaries"][0]["document_type"] == "PAN Card"
    assert result["page_summaries"][0]["rule_id"] == "PAN_NUMBER_MISMATCH"
    assert "Expected value was: ABCDE1234F." in result["page_summaries"][0]["summary_points"]
    assert (
        result["page_summaries"][0]["problem_description"]
        == "PAN number does not match ground truth."
    )


def test_summarize_exceptions():
    anomalies = [{"severity": "HIGH", "rule_id": "TEST_RULE"}]
    result_str = summarize_exceptions(anomalies)
    assert result_str is not None
    assert "exception(s) require review" in result_str


def test_llm_output_contract_is_json_not_toon():
    """Input-TOON / output-JSON rule (ws-g): prompts must request JSON output."""
    from services.llm_page_classifier import _build_classifier_prompt
    from services.llm_service import _build_bilingual_prompt
    from services.structured_llm_classifier import build_structured_classifier_prompt

    page_prompt = _build_classifier_prompt("PAN ABCDE1234F")
    assert "JSON" in page_prompt
    assert "document_type" in page_prompt

    bilingual = _build_bilingual_prompt([{"code": "DATA_MISSING", "severity": "LOW"}], {})
    assert '{"en": "...", "hi": "..."}' in bilingual

    structured = build_structured_classifier_prompt(
        deterministic_document_type="Unknown",
        structured_fields={"pan_number": "ABCDE1234F"},
        ocr_text="PAN card",
    )
    assert "JSON" in structured
