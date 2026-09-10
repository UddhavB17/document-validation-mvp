import json

import database.db as db
from database.db import get_connection, init_db
from services.llm_service import (
    _extract_response_text,
    build_bilingual_fallback,
    generate_explanation,
    generate_summaries,
    parse_bilingual_summary,
    summarize_exceptions,
)


def test_summarize_exceptions_handles_empty_list() -> None:
    assert summarize_exceptions([]) is None


def test_llm_skipped_for_clean_file() -> None:
    assert generate_explanation([], {}) is None


def test_extracts_local_llm_response_text() -> None:
    assert _extract_response_text({"response": "Manual review needed."}) == "Manual review needed."


def test_extracts_open_source_api_response_text() -> None:
    payload = {"choices": [{"message": {"content": "Send back to branch."}}]}
    assert _extract_response_text(payload) == "Send back to branch."


def _fresh_db_with_application(monkeypatch, tmp_path) -> int:
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "summaries.db")
    init_db()
    with get_connection() as connection:
        row = connection.execute(
            "INSERT INTO applications (loan_id, applicant_name, status) "
            "VALUES (?, ?, ?) RETURNING id",
            ("LAP-1", "Ramesh Kumar", "uploaded"),
        ).fetchone()
        return int(row["id"])


def _llm_call_count() -> int:
    with get_connection() as connection:
        row = connection.execute("SELECT COUNT(*) AS n FROM llm_calls").fetchone()
        return int(row["n"])


def test_generate_summaries_bilingual_json_happy_path(monkeypatch, tmp_path) -> None:
    application_id = _fresh_db_with_application(monkeypatch, tmp_path)
    monkeypatch.setattr("services.llm_service.llm_provider", lambda: "gemini")
    monkeypatch.setattr(
        "services.llm_service.call_llm_messages",
        lambda messages, **kwargs: json.dumps(
            {"en": "Two small issues need a quick check.", "hi": "दो छोटी समस्याओं की जाँच आवश्यक है।"}
        ),
    )
    context = {"findings": [{"code": "DATA_MISSING", "severity": "LOW"}], "ground_truth": {}}

    result = generate_summaries(application_id, context)

    assert result["en"] == "Two small issues need a quick check."
    assert "जाँच" in result["hi"]
    with get_connection() as connection:
        row = connection.execute(
            "SELECT ops_summary_en, ops_summary_hi FROM applications WHERE id = ?",
            (application_id,),
        ).fetchone()
    assert row["ops_summary_en"] == result["en"]
    assert row["ops_summary_hi"] == result["hi"]


def test_generate_summaries_malformed_json_uses_fallback(monkeypatch, tmp_path) -> None:
    application_id = _fresh_db_with_application(monkeypatch, tmp_path)
    monkeypatch.setattr("services.llm_service.llm_provider", lambda: "gemini")
    monkeypatch.setattr(
        "services.llm_service.call_llm_messages",
        lambda messages, **kwargs: "not json at all",
    )
    context = {"findings": [{"code": "NAME_MISMATCH", "severity": "HIGH"}]}

    result = generate_summaries(application_id, context)

    assert result == build_bilingual_fallback(context["findings"])
    assert "1 issue(s)" in result["en"]


def test_generate_summaries_provider_none_uses_fallback_and_records_nothing(
    monkeypatch, tmp_path
) -> None:
    application_id = _fresh_db_with_application(monkeypatch, tmp_path)
    monkeypatch.setattr("services.llm_service.llm_provider", lambda: "none")

    def _must_not_call(messages, **kwargs):  # pragma: no cover - guard
        raise AssertionError("LLM must not be called when provider is none")

    monkeypatch.setattr("services.llm_service.call_llm_messages", _must_not_call)

    result = generate_summaries(application_id, {"findings": []})

    assert "no issues found" in result["en"]
    assert _llm_call_count() == 0


def test_parse_bilingual_summary_rejects_bad_payloads() -> None:
    assert parse_bilingual_summary("") is None
    assert parse_bilingual_summary('{"en": "only english"}') is None
    assert parse_bilingual_summary('{"en": "ok", "hi": "no devanagari here"}') is None
    assert parse_bilingual_summary(json.dumps({"en": "x" * 6001, "hi": "जाँच"})) is None
    good = parse_bilingual_summary('```json\n{"en": "All good.", "hi": "सब ठीक है।"}\n```')
    assert good == {"en": "All good.", "hi": "सब ठीक है।"}
