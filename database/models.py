"""Database schema setup.

Tables:
  applications  – one row per uploaded loan file.
  exceptions    – one row per validation exception found.
  audit_log     – immutable event trail for compliance.

Run initialize_schema() once on startup (called from main.py on_startup).
"""

from database.db import get_connection


def initialize_schema() -> None:
    """Create all tables if they do not already exist."""
    with get_connection() as conn:

        # ── applications ──────────────────────────
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS applications (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                loan_id          TEXT    NOT NULL,
                applicant_name   TEXT,
                coapplicant_name TEXT,
                product_type     TEXT,
                branch           TEXT,
                status           TEXT    NOT NULL DEFAULT 'uploaded',
                llm_summary      TEXT,
                created_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        # ── exceptions ────────────────────────────
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS exceptions (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                application_id   INTEGER NOT NULL,
                document_name    TEXT,
                field_name       TEXT,
                issue_type       TEXT    NOT NULL,
                expected_value   TEXT,
                actual_value     TEXT,
                severity         TEXT    NOT NULL DEFAULT 'medium',
                detail           TEXT,
                created_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (application_id) REFERENCES applications (id)
            )
            """
        )

        # ── audit_log ─────────────────────────────
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_log (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                application_id   INTEGER,
                action           TEXT    NOT NULL,
                metadata         TEXT,
                created_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (application_id) REFERENCES applications (id)
            )
            """
        )

        conn.commit()
