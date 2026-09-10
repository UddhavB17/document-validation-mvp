"""Per-call LLM token/cost accounting table (contracts §3, owned by ws-a).

Registered with the schema registry at import time; imported once from
``database/__init__.py``. Writers live in ws-g (``services/llm_client.py``).
"""

from __future__ import annotations

from database.schema_registry import register

LLM_CALLS_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS llm_calls (
        id INTEGER PRIMARY KEY,
        application_id INTEGER REFERENCES applications(id),
        provider TEXT,
        model TEXT,
        purpose TEXT,
        tokens_in INTEGER,
        tokens_out INTEGER,
        duration_ms INTEGER,
        est_cost_usd REAL,
        ok INTEGER NOT NULL DEFAULT 1,
        error TEXT,
        created_at TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_llm_calls_application_id ON llm_calls(application_id)",
    "CREATE INDEX IF NOT EXISTS idx_llm_calls_model ON llm_calls(model)",
    "CREATE INDEX IF NOT EXISTS idx_llm_calls_created_at ON llm_calls(created_at)",
]

register(LLM_CALLS_STATEMENTS)
