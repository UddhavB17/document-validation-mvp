from services.llm_service import _extract_response_text, generate_explanation, summarize_exceptions


def test_summarize_exceptions_handles_empty_list() -> None:
    assert summarize_exceptions([]) is None


def test_llm_skipped_for_clean_file() -> None:
    assert generate_explanation([], {}) is None


def test_extracts_local_llm_response_text() -> None:
    assert _extract_response_text({"response": "Manual review needed."}) == "Manual review needed."


def test_extracts_open_source_api_response_text() -> None:
    payload = {"choices": [{"message": {"content": "Send back to branch."}}]}
    assert _extract_response_text(payload) == "Send back to branch."
