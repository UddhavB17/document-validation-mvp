"""Accounting tests (ws-g-gemini-llm): rows per attempt, cost math, aggregation."""

from __future__ import annotations

import database.db as db
from database.db import get_connection, init_db
from services import llm_accounting


def _fresh_db(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "accounting.db"
    monkeypatch.setattr(db, "DATABASE_PATH", db_path)
    init_db()


def test_record_call_writes_row_with_cost(monkeypatch, tmp_path) -> None:
    _fresh_db(monkeypatch, tmp_path)
    row_id = llm_accounting.record_call(
        "gemini", "gemini-2.5-flash", "summary_en", 1000, 500, 120, None, True,
    )
    assert row_id is not None
    with get_connection() as connection:
        row = connection.execute("SELECT * FROM llm_calls WHERE id = ?", (row_id,)).fetchone()
    assert row["provider"] == "gemini"
    assert row["purpose"] == "summary_en"
    assert row["tokens_in"] == 1000
    assert row["tokens_out"] == 500
    assert row["ok"] in (1, True)
    # (1000 * 0.30 + 500 * 2.50) / 1e6
    assert row["est_cost_usd"] == round((1000 * 0.30 + 500 * 2.50) / 1_000_000, 6)


def test_record_call_unknown_model_cost_null(monkeypatch, tmp_path) -> None:
    _fresh_db(monkeypatch, tmp_path)
    row_id = llm_accounting.record_call(
        "ollama", "some-future-model-99b", "verification", 10, 5, 50, None, False, "boom",
    )
    assert row_id is not None
    with get_connection() as connection:
        row = connection.execute("SELECT * FROM llm_calls WHERE id = ?", (row_id,)).fetchone()
    assert row["est_cost_usd"] is None
    assert row["ok"] in (0, False)
    assert row["error"] == "boom"


def test_summarise_costs_aggregates_per_model(monkeypatch, tmp_path) -> None:
    _fresh_db(monkeypatch, tmp_path)
    llm_accounting.record_call("gemini", "gemini-2.5-flash", "summary_en", 1_000_000, 0, 10, None, True)
    llm_accounting.record_call("gemini", "gemini-2.5-flash", "eval", 0, 1_000_000, 10, None, True)
    llm_accounting.record_call("gemini", "gemini-2.5-pro", "summary_en", 100, 100, 10, None, True)

    summary = {entry["model"]: entry for entry in llm_accounting.summarise_costs()}
    assert summary["gemini-2.5-flash"]["calls"] == 2
    assert summary["gemini-2.5-flash"]["tokens_in"] == 1_000_000
    assert summary["gemini-2.5-flash"]["tokens_out"] == 1_000_000
    assert summary["gemini-2.5-flash"]["usd"] == round(0.30 + 2.50, 6)
    assert summary["gemini-2.5-pro"]["calls"] == 1


def test_pricing_override_via_env(monkeypatch, tmp_path) -> None:
    _fresh_db(monkeypatch, tmp_path)
    monkeypatch.setenv("GEMINI_PRICING_JSON", '{"gemini-2.5-flash": [1.0, 4.0]}')
    row_id = llm_accounting.record_call(
        "gemini", "gemini-2.5-flash", "eval", 1_000_000, 1_000_000, 10, None, True,
    )
    with get_connection() as connection:
        row = connection.execute("SELECT * FROM llm_calls WHERE id = ?", (row_id,)).fetchone()
    assert row["est_cost_usd"] == 5.0
