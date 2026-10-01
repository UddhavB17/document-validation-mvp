"""Manual NDC checklist ticks, one row per application/row/role (tmp/user-portal-ux).

A row exists = the ops role checked that NDC row. System-found rows never
need a manual tick to count as complete; completeness is computed in
``services/ops_ndc.py`` from system status plus these rows.

Registered with the schema registry at import time; imported once from
``database/__init__.py``.
"""

from __future__ import annotations

from database.schema_registry import register

OPS_NDC_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS ops_ndc_checks (
        application_id INTEGER NOT NULL REFERENCES applications(id),
        s_no INTEGER NOT NULL,
        role TEXT NOT NULL,
        checked_by INTEGER,
        checked_at TEXT,
        PRIMARY KEY (application_id, s_no, role)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_ops_ndc_checks_application_id ON ops_ndc_checks(application_id)",
]

register(OPS_NDC_STATEMENTS)
