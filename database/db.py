"""SQLite connection helpers.

The database file lives at DATABASE_PATH (default: data/dmef.db).
Override by setting DATABASE_PATH in your .env file.
"""

import os
import sqlite3
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DATABASE_PATH = Path(os.getenv("DATABASE_PATH", "data/dmef.db"))


def get_connection() -> sqlite3.Connection:
    """Open the SQLite database and return rows addressable by column name."""
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH, timeout=30.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA busy_timeout = 30000")
    return connection


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
        for statement in INDEX_STATEMENTS:
            connection.execute(statement)
        seed_settings(connection)


def seed_settings(connection: sqlite3.Connection) -> None:
    defaults = [
        ("llm_enabled", "false", "bool", "llm", "Enable LLM Verification", "Enable LLM verification checks and checklist engine queries."),
        ("llm_provider", "ollama", "str", "llm", "LLM Provider", "Select the LLM backend provider (e.g. ollama, openai, gemini)."),
        ("llm_model", "llama3.2", "str", "llm", "Model Name", "Name of the LLM model to run queries against."),
        ("min_confidence", "0.70", "float", "classification", "Min Classification Confidence", "Minimum confidence score required to auto-classify a page."),
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
