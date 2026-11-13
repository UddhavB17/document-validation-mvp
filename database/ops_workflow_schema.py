"""Ops workflow persistence for ownership, review checks and document requests."""

from database.schema_registry import register

OPS_WORKFLOW_SCHEMA_STATEMENTS: list[str] = [
    """CREATE TABLE IF NOT EXISTS ops_cases (
        application_id INTEGER PRIMARY KEY REFERENCES applications(id),
        owner_user_id INTEGER REFERENCES users(id),
        workflow_state TEXT NOT NULL DEFAULT 'ready',
        waiting_reason TEXT,
        ready_at TEXT,
        returned_at TEXT,
        first_started_at TEXT,
        first_outcome_at TEXT,
        completed_at TEXT,
        updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS ops_case_events (
        id INTEGER PRIMARY KEY,
        application_id INTEGER NOT NULL REFERENCES applications(id),
        actor_user_id INTEGER REFERENCES users(id),
        action TEXT NOT NULL,
        reason TEXT,
        details_json TEXT NOT NULL DEFAULT '{}',
        occurred_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS ops_review_checks (
        application_id INTEGER NOT NULL REFERENCES applications(id),
        check_key TEXT NOT NULL,
        evidence_revision TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('checked','exception_confirmed','needs_help')),
        note TEXT,
        actor_user_id INTEGER REFERENCES users(id),
        updated_at TEXT NOT NULL,
        PRIMARY KEY(application_id, check_key)
    )""",
    """CREATE TABLE IF NOT EXISTS ops_document_requests (
        id INTEGER PRIMARY KEY,
        application_id INTEGER NOT NULL REFERENCES applications(id),
        owner_user_id INTEGER REFERENCES users(id),
        message TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('open','resolved','cancelled')),
        follow_up_at TEXT,
        created_by INTEGER REFERENCES users(id),
        opened_at TEXT NOT NULL,
        resolved_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS ops_document_request_items (
        id INTEGER PRIMARY KEY,
        request_id INTEGER NOT NULL REFERENCES ops_document_requests(id),
        item TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('requested','received','outstanding')),
        uploaded_file_id INTEGER REFERENCES uploaded_files(id),
        updated_at TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_ops_cases_queue ON ops_cases(workflow_state, returned_at, ready_at)",
    "CREATE INDEX IF NOT EXISTS idx_ops_cases_owner ON ops_cases(owner_user_id, workflow_state)",
    "CREATE INDEX IF NOT EXISTS idx_ops_events_application ON ops_case_events(application_id, occurred_at)",
    "CREATE INDEX IF NOT EXISTS idx_ops_requests_application ON ops_document_requests(application_id, status)",
]

register(OPS_WORKFLOW_SCHEMA_STATEMENTS)
