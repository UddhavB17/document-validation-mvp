"""SQLite schema statements for DMEF."""

SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS applications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        loan_id TEXT NOT NULL,
        applicant_name TEXT,
        coapplicant_name TEXT,
        product_type TEXT,
        branch TEXT,
        status TEXT NOT NULL DEFAULT 'uploaded',
        llm_summary TEXT,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS uploaded_files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        application_id INTEGER REFERENCES applications(id),
        file_path TEXT,
        original_filename TEXT,
        file_size_kb REAL,
        total_pages INTEGER,
        digital_pages INTEGER,
        scanned_pages INTEGER,
        uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ground_truth (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        application_id INTEGER REFERENCES applications(id),
        applicant_name TEXT,
        pan_number TEXT,
        loan_amount TEXT,
        phone TEXT,
        address TEXT,
        product_type TEXT,
        raw_json TEXT,
        extracted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS pages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        application_id INTEGER REFERENCES applications(id),
        page_number INTEGER,
        page_type TEXT CHECK(page_type IN ('digital', 'scanned')),
        image_path TEXT,
        is_readable BOOLEAN,
        ocr_text TEXT,
        ocr_confidence REAL,
        document_type TEXT,
        classification_confidence REAL,
        detection_method TEXT DEFAULT 'detected',
        detected_page_number INTEGER,
        extracted_fields TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS validation_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        application_id INTEGER REFERENCES applications(id),
        rule_id TEXT,
        s_no INTEGER,
        severity TEXT,
        document_type TEXT,
        expected_value TEXT,
        found_value TEXT,
        page_number INTEGER,
        reason TEXT,
        status TEXT DEFAULT 'open',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS reviewer_decisions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        application_id INTEGER REFERENCES applications(id),
        decision TEXT,
        reviewer_note TEXT NOT NULL,
        decided_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS exceptions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        application_id INTEGER NOT NULL,
        document_name TEXT,
        field_name TEXT,
        issue_type TEXT NOT NULL,
        expected_value TEXT,
        actual_value TEXT,
        severity TEXT NOT NULL DEFAULT 'medium',
        detail TEXT,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (application_id) REFERENCES applications (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        application_id INTEGER REFERENCES applications(id),
        action TEXT NOT NULL,
        details TEXT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS pipeline_progress (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        application_id INTEGER NOT NULL UNIQUE REFERENCES applications(id),
        stage TEXT NOT NULL DEFAULT 'queued',
        total_pages INTEGER NOT NULL DEFAULT 0,
        digital_pages INTEGER NOT NULL DEFAULT 0,
        scanned_pages INTEGER NOT NULL DEFAULT 0,
        processed_pages INTEGER NOT NULL DEFAULT 0,
        current_page INTEGER,
        percentage REAL NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'processing',
        message TEXT,
        error TEXT,
        started_at TEXT,
        updated_at TEXT,
        completed_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS pipeline_jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        application_id INTEGER NOT NULL REFERENCES applications(id),
        job_type TEXT NOT NULL DEFAULT 'pdf_pipeline',
        status TEXT NOT NULL DEFAULT 'queued',
        error TEXT,
        created_at TEXT NOT NULL,
        started_at TEXT,
        completed_at TEXT
    )
    """,
]

MIGRATION_STATEMENTS = [
    "ALTER TABLE validation_results ADD COLUMN s_no INTEGER",
    "ALTER TABLE pages ADD COLUMN detection_method TEXT DEFAULT 'detected'",
    "ALTER TABLE pages ADD COLUMN detected_page_number INTEGER",
]

INDEX_STATEMENTS = [
    "CREATE INDEX IF NOT EXISTS idx_uploaded_files_application_id ON uploaded_files(application_id)",
    "CREATE INDEX IF NOT EXISTS idx_ground_truth_application_id ON ground_truth(application_id)",
    "CREATE INDEX IF NOT EXISTS idx_pages_application_id ON pages(application_id)",
    "CREATE INDEX IF NOT EXISTS idx_validation_results_application_id ON validation_results(application_id)",
    "CREATE INDEX IF NOT EXISTS idx_reviewer_decisions_application_id ON reviewer_decisions(application_id)",
    "CREATE INDEX IF NOT EXISTS idx_exceptions_application_id ON exceptions(application_id)",
    "CREATE INDEX IF NOT EXISTS idx_audit_log_application_id ON audit_log(application_id)",
    "CREATE INDEX IF NOT EXISTS idx_pipeline_progress_application_id ON pipeline_progress(application_id)",
    "CREATE INDEX IF NOT EXISTS idx_pipeline_jobs_application_id ON pipeline_jobs(application_id)",
    "CREATE INDEX IF NOT EXISTS idx_pipeline_jobs_status ON pipeline_jobs(status)",
]


def initialize_schema() -> None:
    """Backward-compatible schema initializer used by older entry points."""
    from database.db import init_db

    init_db()
