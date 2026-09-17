"""Persisted human review state for individual operations findings.

Review state is intentionally separate from ``validation_results`` and from
LLM dismissals. A finding revision gets a deterministic opaque item id, so a
reprocessed finding cannot inherit an approval from an older revision.
"""

from __future__ import annotations

from database.schema_registry import register

OPS_REVIEW_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS ops_review_items (
        item_id TEXT PRIMARY KEY,
        application_id INTEGER NOT NULL REFERENCES applications(id),
        validation_result_id INTEGER NOT NULL REFERENCES validation_results(id),
        finding_revision TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'reviewed')),
        disposition TEXT CHECK(disposition IN ('correct', 'reopen')),
        reviewer_id INTEGER REFERENCES users(id),
        reviewed_at TEXT,
        note TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(application_id, validation_result_id, finding_revision)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_ops_review_items_application_id ON ops_review_items(application_id)",
    "CREATE INDEX IF NOT EXISTS idx_ops_review_items_application_status ON ops_review_items(application_id, status)",
]

register(OPS_REVIEW_STATEMENTS)
