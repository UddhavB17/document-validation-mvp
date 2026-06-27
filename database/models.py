"""Database schema setup."""

from database.db import get_connection


def initialize_schema() -> None:
    with get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                loan_id TEXT NOT NULL,
                applicant_name TEXT,
                coapplicant_name TEXT,
                product_type TEXT,
                branch TEXT,
                status TEXT DEFAULT 'uploaded',
                llm_summary TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS exceptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                application_id INTEGER NOT NULL,
                document_name TEXT,
                field_name TEXT,
                issue_type TEXT,
                expected_value TEXT,
                actual_value TEXT,
                severity TEXT DEFAULT 'medium',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(application_id) REFERENCES applications(id)
            )
            """
        )
