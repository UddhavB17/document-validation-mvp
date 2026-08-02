"""SQLite connection helpers.

The database file lives at DATABASE_PATH (default: data/dmef.db).
Override by setting DATABASE_PATH in your .env file.
"""

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DATABASE_PATH = Path(os.getenv("DATABASE_PATH", "data/dmef.db"))


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    """Yield a configured SQLite connection and always close it afterward."""
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH, timeout=30.0)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 30000")
        try:
            yield connection
        except BaseException:
            connection.rollback()
            raise
        else:
            connection.commit()
    finally:
        connection.close()


def init_db() -> None:
    """Create all DMEF tables and indexes if they do not already exist."""
    from database.models import INDEX_STATEMENTS, MIGRATION_STATEMENTS, SCHEMA_STATEMENTS

    with get_connection() as connection:
        for statement in SCHEMA_STATEMENTS:
            connection.execute(statement)
        for statement in MIGRATION_STATEMENTS:
            try:
                connection.execute(statement)
            except sqlite3.OperationalError as exc:
                if "duplicate column name" not in str(exc).lower():
                    raise
        _migrate_ocr_route_events_for_google_vision(connection)
        _migrate_pages_ocr_route_for_google_vision(connection)
        for statement in INDEX_STATEMENTS:
            connection.execute(statement)
        seed_settings(connection)


def _table_sql(connection: sqlite3.Connection, table_name: str) -> str:
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    if not row:
        return ""
    return str(row["sql"] if isinstance(row, sqlite3.Row) else row[0] or "")


def _ocr_route_check_needs_google_vision(table_sql: str) -> bool:
    """True when a legacy ocr_route CHECK exists but omits google_vision."""
    if not table_sql or "google_vision" in table_sql:
        return False
    normalized = " ".join(table_sql.lower().split())
    return "check(ocr_route in (" in normalized or "check(requested_route in (" in normalized or "check(route_used in (" in normalized


def _migrate_ocr_route_events_for_google_vision(connection: sqlite3.Connection) -> None:
    """Expand the legacy route CHECK constraints without losing telemetry."""
    table_sql = _table_sql(connection, "ocr_route_events")
    if not _ocr_route_check_needs_google_vision(table_sql):
        return

    connection.execute("ALTER TABLE ocr_route_events RENAME TO ocr_route_events_legacy")
    connection.execute(
        """
        CREATE TABLE ocr_route_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id TEXT NOT NULL,
            document_type TEXT,
            page_number INTEGER NOT NULL,
            event_type TEXT NOT NULL CHECK(event_type IN ('processing', 'escalation')),
            requested_route TEXT NOT NULL
                CHECK(requested_route IN ('fast', 'structured', 'google_vision')),
            route_used TEXT NOT NULL
                CHECK(route_used IN ('fast', 'structured', 'google_vision')),
            reason TEXT,
            original_confidence REAL,
            duration_ms INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    connection.execute(
        """
        INSERT INTO ocr_route_events (
            id, document_id, document_type, page_number, event_type,
            requested_route, route_used, reason, original_confidence,
            duration_ms, created_at
        )
        SELECT id, document_id, document_type, page_number, event_type,
               requested_route, route_used, reason, original_confidence,
               duration_ms, created_at
        FROM ocr_route_events_legacy
        """
    )
    connection.execute("DROP TABLE ocr_route_events_legacy")


def _migrate_pages_ocr_route_for_google_vision(connection: sqlite3.Connection) -> None:
    """Expand pages.ocr_route CHECK so Google Vision routes can be persisted."""
    table_sql = _table_sql(connection, "pages")
    if not _ocr_route_check_needs_google_vision(table_sql):
        return

    # SQLite only honors foreign_keys changes outside an open transaction.
    connection.commit()
    connection.execute("PRAGMA foreign_keys = OFF")
    try:
        connection.execute("ALTER TABLE pages RENAME TO pages_legacy")
        connection.execute(
            """
            CREATE TABLE pages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                application_id INTEGER REFERENCES applications(id),
                page_number INTEGER,
                page_type TEXT CHECK(page_type IN ('digital', 'scanned')),
                image_path TEXT,
                is_readable BOOLEAN,
                ocr_text TEXT,
                ocr_confidence REAL,
                ocr_route TEXT CHECK(ocr_route IN ('fast', 'structured', 'google_vision')),
                ocr_escalated BOOLEAN NOT NULL DEFAULT 0,
                ocr_processing_time_ms INTEGER NOT NULL DEFAULT 0,
                structured_content TEXT,
                document_type TEXT,
                classification_confidence REAL,
                detection_method TEXT DEFAULT 'detected',
                detected_page_number INTEGER,
                extracted_fields TEXT
            )
            """
        )
        connection.execute(
            """
            INSERT INTO pages (
                id, application_id, page_number, page_type, image_path, is_readable,
                ocr_text, ocr_confidence, ocr_route, ocr_escalated, ocr_processing_time_ms,
                structured_content, document_type, classification_confidence,
                detection_method, detected_page_number, extracted_fields
            )
            SELECT
                id, application_id, page_number, page_type, image_path, is_readable,
                ocr_text, ocr_confidence, ocr_route,
                COALESCE(ocr_escalated, 0),
                COALESCE(ocr_processing_time_ms, 0),
                structured_content, document_type, classification_confidence,
                COALESCE(detection_method, 'detected'),
                detected_page_number, extracted_fields
            FROM pages_legacy
            """
        )
        connection.execute("DROP TABLE pages_legacy")
    finally:
        connection.execute("PRAGMA foreign_keys = ON")


def seed_settings(connection: sqlite3.Connection) -> None:
    defaults = [
        ("llm_enabled", "false", "bool", "llm", "Enable LLM Verification", "Enable LLM verification checks and checklist engine queries."),
        ("llm_provider", "ollama", "str", "llm", "LLM Provider", "Select the LLM backend provider (e.g. ollama, openai, gemini)."),
        ("llm_model", "llama3.2", "str", "llm", "Model Name", "Name of the LLM model to run queries against."),
        ("min_confidence", "0.70", "float", "classification", "Min Classification Confidence", "Minimum confidence score required to auto-classify a page."),
        ("ocr.provider", "local", "str", "ocr", "OCR Provider", "Choose local OCR, Google Vision API OCR, or automatic fallback."),
        ("google.vision.auth", "auto", "str", "ocr", "Google Vision Auth Mode", "Use API key, Application Default Credentials, or automatic Google Vision authentication."),
        ("google.vision.api_key", "", "secret", "ocr", "Google Vision API Key", "Optional Google Vision API key used only for OCR calls."),
        ("google.vision.feature", "DOCUMENT_TEXT_DETECTION", "str", "ocr", "Google Vision OCR Feature", "Google Vision feature used for OCR."),
        ("google.vision.timeout.seconds", "60", "int", "ocr", "Google Vision Timeout", "Timeout in seconds for each Google Vision OCR request."),
        ("google.vision.max_attempts", "3", "int", "ocr", "Google Vision Retry Attempts", "Retry transient Google Vision network and service failures before flagging a page."),
        ("google.vision.api_endpoint", "", "str", "ocr", "Google Vision API Endpoint", "Optional custom client endpoint for Google Vision."),
        ("google.vision.rest_url", "https://vision.googleapis.com/v1/images:annotate", "str", "ocr", "Google Vision REST URL", "REST endpoint used when authenticating Google Vision with an API key."),
        ("required_fields.pan", '["pan_number", "applicant_name", "date_of_birth"]', "json", "fields", "PAN Card Required Fields", "Fields required to validate a PAN Card."),
        ("required_fields.aadhaar", '["aadhaar_number", "applicant_name", "date_of_birth", "address", "pin_code"]', "json", "fields", "Aadhaar Required Fields", "Fields required to validate Aadhaar."),
        ("required_fields.voter_id", '["voter_id_number", "applicant_name", "date_of_birth", "address"]', "json", "fields", "Voter ID Required Fields", "Fields required to validate a Voter ID."),
        ("required_fields.driving_license", '["dl_number", "applicant_name", "date_of_birth", "validity_date", "is_expired"]', "json", "fields", "Driving License Required Fields", "Fields required to validate a Driving License."),
        ("required_fields.sanction_letter", '["applicant_name", "loan_amount"]', "json", "fields", "Sanction Letter Required Fields", "Fields required to validate a Sanction Letter."),
        ("required_fields.loan_agreement", '["applicant_name", "loan_amount"]', "json", "fields", "Loan Agreement Required Fields", "Fields required to validate a Loan Agreement."),
        ("required_fields.cibil_report", '["applicant_name"]', "json", "fields", "CIBIL Required Fields", "Fields required to validate a CIBIL report."),
        ("required_fields.crif_report", '["applicant_name"]', "json", "fields", "CRIF Required Fields", "Fields required to validate a CRIF report."),
        ("required_fields.bank_statement", '["applicant_name"]', "json", "fields", "Bank Statement Required Fields", "Fields required to validate a Bank Statement."),
        ("required_fields.passbook", '["applicant_name"]', "json", "fields", "Passbook Required Fields", "Fields required to validate a Passbook."),
        ("required_fields.cheque", '["applicant_name"]', "json", "fields", "Cheque Required Fields", "Fields required to validate a Cheque."),
        ("required_fields.salary_slip", '["applicant_name", "salary_month", "net_salary"]', "json", "fields", "Salary Slip Required Fields", "Fields required to validate a Salary Slip."),
        ("required_fields.stamp_duty", '["stamp_duty_amount", "stamp_paper_number", "first_party", "second_party"]', "json", "fields", "Stamp Duty Required Fields", "Fields required to validate a Stamp Duty document."),
        ("required_fields.insurance_consent", '["is_consent_given", "premium_amount"]', "json", "fields", "Insurance Consent Required Fields", "Fields required to validate Insurance Consent."),
        ("required_fields.clearance_report", '["search_result", "debtor_name", "pan_number"]', "json", "fields", "Clearance Report Required Fields", "Fields required to validate a Clearance/CERSAI Report."),
        ("required_fields.nach_form", '["account_number", "ifsc", "mandate_limit"]', "json", "fields", "NACH Form Required Fields", "Fields required to validate a NACH Mandate Form."),
        ("required_fields.utility_bill", '["applicant_name", "address", "pin_code"]', "json", "fields", "Utility Bill Required Fields", "Fields required to validate a Utility Bill."),
        ("required_fields.application_form", '["applicant_name", "aadhaar_number", "pan_number", "date_of_birth", "phone_number", "address", "pin_code", "loan_amount"]', "json", "fields", "Application Form Required Fields", "Fields required to validate an Application Form."),
    ]
    for key, val, val_type, cat, lbl, desc in defaults:
        connection.execute(
            """
            INSERT OR IGNORE INTO system_settings 
            (config_key, config_value, value_type, category, label, description) 
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (key, val, val_type, cat, lbl, desc)
        )
