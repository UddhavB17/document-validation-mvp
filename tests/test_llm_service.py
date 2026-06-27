from services.llm_service import summarize_exceptions


def test_summarize_exceptions_handles_empty_list() -> None:
    assert summarize_exceptions([]) == "No exceptions found."
