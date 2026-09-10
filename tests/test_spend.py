"""Spend rollup tests: LLM + Vision totals with free tiers excluded."""

from __future__ import annotations

from pathlib import Path

import pytest

import database.db as db
from database.db import get_connection, init_db
from services.spend import spend_summary


def _fresh_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "dmef.db")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    init_db()
    with get_connection() as connection:
        connection.execute(
            "INSERT INTO applications (loan_id, applicant_name, product_type, status, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            ("SPEND-1", "Spend Test", "LAP", "completed", "2026-09-01 10:00:00"),
        )


def _seed_llm_call(cost: float) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO llm_calls
                (provider, model, purpose, tokens_in, tokens_out, duration_ms,
                 application_id, ok, error, est_cost_usd, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "gemini",
                "gemini-2.5-flash",
                "summary_en",
                100,
                50,
                10,
                1,
                True,
                None,
                cost,
                "2026-09-01T10:00:00+00:00",
            ),
        )


def _seed_vision_units(month: str, units: int) -> None:
    with get_connection() as connection:
        for page in range(units):
            connection.execute(
                """
                INSERT INTO ocr_route_events
                    (document_id, document_type, page_number, event_type,
                     requested_route, route_used, reason, original_confidence,
                     duration_ms, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"9:{page}",
                    "PAN",
                    page,
                    "processing",
                    "google_vision",
                    "google_vision",
                    None,
                    0.9,
                    100,
                    f"{month}-15 10:00:00",
                ),
            )


def test_empty_database_reports_zero_spend(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fresh_db(tmp_path, monkeypatch)

    summary = spend_summary()

    assert summary["currency"] == "USD"
    assert summary["total_usd"] == 0.0
    assert summary["llm"] == {"calls": 0, "usd": 0.0}
    assert summary["vision"]["units_total"] == 0
    assert summary["vision"]["billable_units"] == 0
    assert summary["vision"]["usd"] == 0.0
    assert summary["vision"]["by_month"] == []


def test_free_tier_pages_are_excluded_from_spend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fresh_db(tmp_path, monkeypatch)
    monkeypatch.setenv("DMEF_VISION_FREE_UNITS_MONTHLY", "1000")
    monkeypatch.setenv("DMEF_VISION_PRICE_PER_1K_USD", "1.50")
    _seed_llm_call(0.004)
    _seed_vision_units("2026-09", 1200)  # 1000 free + 200 billable
    _seed_vision_units("2026-08", 400)  # entirely free

    summary = spend_summary()

    assert summary["llm"] == {"calls": 1, "usd": 0.004}
    assert summary["vision"]["units_total"] == 1600
    assert summary["vision"]["free_units"] == 1400
    assert summary["vision"]["billable_units"] == 200
    assert summary["vision"]["usd"] == 0.30
    assert summary["total_usd"] == 0.304
    by_month = {row["month"]: row for row in summary["vision"]["by_month"]}
    assert by_month["2026-09"]["billable_units"] == 200
    assert by_month["2026-08"]["billable_units"] == 0
    assert by_month["2026-08"]["usd"] == 0.0
