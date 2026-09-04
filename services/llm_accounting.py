"""Token and cost accounting for every LLM call.

Implemented by ``ws-g-gemini-llm``. Every attempt made through
``services.llm_client.call_llm_messages`` is recorded here in the
``llm_calls`` table so the admin UI and the model bake-off script can report
tokens and estimated cost per model.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

# prices as of 2026-09-04 (USD per 1M tokens: input, output).
# Overridable at runtime with GEMINI_PRICING_JSON, e.g.
# GEMINI_PRICING_JSON='{"gemini-2.5-flash": [0.30, 2.50]}'.
MODEL_PRICES_USD_PER_1M: dict[str, tuple[float, float]] = {
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-pro": (1.25, 10.00),
    "gemini-2.0-flash": (0.10, 0.40),
    "gemini-1.5-flash": (0.075, 0.30),
    "gemini-1.5-pro": (1.25, 5.00),
    "gpt-5.6-luna": (2.00, 8.00),
    "gpt-4o": (2.50, 10.00),
    "llama3.1": (0.0, 0.0),
    "llama3.2": (0.0, 0.0),
    "qwen2.5": (0.0, 0.0),
}

LLM_CALLS_SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS llm_calls (
        id INTEGER PRIMARY KEY,
        provider TEXT NOT NULL,
        model TEXT NOT NULL,
        purpose TEXT NOT NULL,
        tokens_in INTEGER NOT NULL DEFAULT 0,
        tokens_out INTEGER NOT NULL DEFAULT 0,
        duration_ms INTEGER NOT NULL DEFAULT 0,
        application_id INTEGER REFERENCES applications(id),
        ok INTEGER NOT NULL DEFAULT 1,
        error TEXT,
        est_cost_usd REAL,
        created_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_llm_calls_application_id ON llm_calls(application_id)",
    "CREATE INDEX IF NOT EXISTS idx_llm_calls_model ON llm_calls(model)",
    "CREATE INDEX IF NOT EXISTS idx_llm_calls_created_at ON llm_calls(created_at)",
]

try:  # registered when imported from database/__init__.py (contracts §3)
    from database.schema_registry import register as _register

    _register(LLM_CALLS_SCHEMA_STATEMENTS)
except Exception:  # noqa: BLE001 - registry unavailable (e.g. partial import)
    logger.debug("llm_calls schema registration deferred", exc_info=True)


def _pricing_table() -> dict[str, tuple[float, float]]:
    table = dict(MODEL_PRICES_USD_PER_1M)
    try:
        from services.config import get_setting

        raw = get_setting("GEMINI_PRICING_JSON")
    except Exception:  # noqa: BLE001 - config unavailable, use built-ins
        return table
    if not raw:
        return table
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        for key, value in dict(parsed).items():
            per_in, per_out = value
            table[str(key)] = (float(per_in), float(per_out))
    except Exception:  # noqa: BLE001 - malformed override, keep built-ins
        logger.warning("Ignoring malformed GEMINI_PRICING_JSON override")
    return table


def estimate_cost_usd(model: str, tokens_in: int, tokens_out: int) -> float | None:
    """Return the estimated USD cost for a model, or None when unknown."""
    table = _pricing_table()
    needle = str(model or "")
    for prefix, (per_in, per_out) in table.items():
        if needle == prefix or needle.startswith(prefix):
            return round((tokens_in * per_in + tokens_out * per_out) / 1_000_000, 6)
    return None


def record_call(
    provider: str,
    model: str,
    purpose: str,
    tokens_in: int,
    tokens_out: int,
    duration_ms: int,
    application_id: int | None,
    ok: bool,
    error: str | None = None,
) -> int | None:
    """Insert one ``llm_calls`` row per attempt. Never raises."""
    try:
        from database.db import get_connection

        cost = estimate_cost_usd(model, int(tokens_in or 0), int(tokens_out or 0))
        created_at = datetime.now(UTC).isoformat()
        with get_connection() as connection:
            row = connection.execute(
                "INSERT INTO llm_calls "
                "(provider, model, purpose, tokens_in, tokens_out, duration_ms, "
                "application_id, ok, error, est_cost_usd, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
                (
                    provider,
                    model,
                    purpose,
                    int(tokens_in or 0),
                    int(tokens_out or 0),
                    int(duration_ms or 0),
                    application_id,
                    bool(ok),
                    error,
                    cost,
                    created_at,
                ),
            ).fetchone()
            return int(row["id"])
    except Exception as exc:  # noqa: BLE001 - accounting must not break LLM calls
        logger.warning("Failed to record llm_calls row: %s", exc)
        return None


def summarise_costs(since: str | None = None) -> list[dict[str, Any]]:
    """Aggregate calls, tokens and cost per model for the admin UI."""
    try:
        from database.db import get_connection

        query = (
            "SELECT model, COUNT(*) AS calls, "
            "COALESCE(SUM(tokens_in), 0) AS tokens_in, "
            "COALESCE(SUM(tokens_out), 0) AS tokens_out, "
            "SUM(est_cost_usd) AS usd FROM llm_calls"
        )
        params: tuple[Any, ...] = ()
        if since:
            query += " WHERE created_at >= ?"
            params = (since,)
        query += " GROUP BY model ORDER BY model"
        with get_connection() as connection:
            rows = connection.execute(query, params).fetchall()
        return [
            {
                "model": row["model"],
                "calls": int(row["calls"]),
                "tokens_in": int(row["tokens_in"]),
                "tokens_out": int(row["tokens_out"]),
                "usd": float(row["usd"]) if row["usd"] is not None else 0.0,
            }
            for row in rows
        ]
    except Exception as exc:  # noqa: BLE001 - report empties, never crash the UI
        logger.warning("Failed to summarise llm costs: %s", exc)
        return []
