"""Total-spend rollup across every processed application.

Two billable meters, both already recorded by the pipeline:

* LLM calls (``llm_calls.est_cost_usd``) — local models (Ollama) price at
  $0, so only API-billed calls contribute.
* Google Vision OCR (``ocr_route_events`` with ``route_used`` =
  ``'google_vision'`` and ``event_type`` = ``'processing'`` — one row per
  scanned page sent to the API). The Vision free tier (first N units per
  calendar month) is subtracted, so free pages never count toward spend.

On-demand local OCR, storage, and the Neon free tier itself cost nothing
per unit and are excluded. Empty tables yield $0.
"""

from __future__ import annotations

import threading
import time
from copy import deepcopy
from typing import Any

from database.db import get_connection
from services.config import get_float, get_int

#: Google Vision DOCUMENT_TEXT_DETECTION list price (USD per 1,000 pages).
#: Overridable with DMEF_VISION_PRICE_PER_1K_USD.
DEFAULT_VISION_PRICE_PER_1K_USD = 1.50

#: Free Vision units per calendar month (Google's free tier). The first N
#: pages each month are excluded from spend. Overridable with
#: DMEF_VISION_FREE_UNITS_MONTHLY.
DEFAULT_VISION_FREE_UNITS_MONTHLY = 1000
_SPEND_CACHE_TTL_SECONDS = 30.0
_spend_cache_lock = threading.Lock()
_spend_cache_at = 0.0
_spend_cache_value: dict[str, Any] | None = None
_spend_cache_database_key: str | None = None


def _table_exists(connection: Any, table: str) -> bool:
    try:
        connection.execute(f"SELECT 1 FROM {table} WHERE 1 = 0").fetchall()
    except Exception:  # noqa: BLE001 - legacy databases predate the table
        return False
    return True


def vision_price_per_1k_usd() -> float:
    """Configured Vision price per 1,000 pages (USD)."""
    return get_float("DMEF_VISION_PRICE_PER_1K_USD", DEFAULT_VISION_PRICE_PER_1K_USD, minimum=0.0)


def vision_free_units_monthly() -> int:
    """Configured free Vision units per calendar month."""
    return get_int("DMEF_VISION_FREE_UNITS_MONTHLY", DEFAULT_VISION_FREE_UNITS_MONTHLY, minimum=0)


def vision_units_by_month() -> list[dict[str, Any]]:
    """Billable Vision API units per calendar month (``YYYY-MM``).

    Counts ``processing`` events routed to Google Vision — one per scanned
    page sent to the API. Months with no usage are absent, never zero-filled.
    """
    with get_connection() as connection:
        return _vision_units_by_month(connection)


def _vision_units_by_month(connection: Any) -> list[dict[str, Any]]:
    if not _table_exists(connection, "ocr_route_events"):
        return []
    try:
        rows = connection.execute(
            "SELECT SUBSTR(created_at, 1, 7) AS month, COUNT(*) AS units "
            "FROM ocr_route_events "
            "WHERE event_type = 'processing' AND route_used = 'google_vision' "
            "GROUP BY month ORDER BY month"
        ).fetchall()
    except Exception:  # noqa: BLE001 - unexpected shape; report no usage
        return []
    return [{"month": str(row["month"]), "units": int(row["units"])} for row in rows]


def llm_totals() -> dict[str, Any]:
    """Total LLM calls and estimated USD across all models."""
    with get_connection() as connection:
        return _llm_totals(connection)


def _llm_totals(connection: Any) -> dict[str, Any]:
    if not _table_exists(connection, "llm_calls"):
        return {"calls": 0, "usd": 0.0}
    try:
        row = connection.execute(
            "SELECT COUNT(*) AS calls, COALESCE(SUM(est_cost_usd), 0) AS usd FROM llm_calls"
        ).fetchone()
    except Exception:  # noqa: BLE001 - unexpected shape; report zeros
        return {"calls": 0, "usd": 0.0}
    return {"calls": int(row["calls"]), "usd": round(float(row["usd"]), 6)}


def spend_summary() -> dict[str, Any]:
    """Total spend so far: LLM + billable Vision, free tiers excluded."""
    global _spend_cache_at, _spend_cache_value, _spend_cache_database_key
    from database import db as database_module

    database_key = str(database_module._engine_key())
    now = time.monotonic()
    with _spend_cache_lock:
        if (
            _spend_cache_value is not None
            and _spend_cache_database_key == database_key
            and now - _spend_cache_at < _SPEND_CACHE_TTL_SECONDS
        ):
            return deepcopy(_spend_cache_value)
    price_per_1k = vision_price_per_1k_usd()
    free_monthly = vision_free_units_monthly()
    months: list[dict[str, Any]] = []
    units_total = 0
    billable_total = 0
    with get_connection() as connection:
        llm = _llm_totals(connection)
        vision_units = _vision_units_by_month(connection)
    for entry in vision_units:
        units = int(entry["units"])
        billable = max(0, units - free_monthly)
        usd = round(billable * price_per_1k / 1000, 6)
        months.append(
            {
                "month": entry["month"],
                "units": units,
                "free_units": min(units, free_monthly),
                "billable_units": billable,
                "usd": usd,
            }
        )
        units_total += units
        billable_total += billable
    vision_usd = round(billable_total * price_per_1k / 1000, 6)
    total_usd = round(float(llm["usd"]) + vision_usd, 6)
    result = {
        "currency": "USD",
        "llm": llm,
        "vision": {
            "units_total": units_total,
            "free_units": units_total - billable_total,
            "billable_units": billable_total,
            "price_per_1k_usd": price_per_1k,
            "free_units_monthly": free_monthly,
            "usd": vision_usd,
            "by_month": months,
        },
        "total_usd": total_usd,
    }
    with _spend_cache_lock:
        _spend_cache_at = time.monotonic()
        _spend_cache_value = result
        _spend_cache_database_key = database_key
    return deepcopy(result)
