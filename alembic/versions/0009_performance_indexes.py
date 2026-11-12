"""Indexes for common operations and telemetry lookups.

Revision ID: 0009_performance_indexes
Revises: 0008_intake_package_error
Create Date: 2026-11-12
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0009_performance_indexes"
down_revision: str | Sequence[str] | None = "0008_intake_package_error"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEXES = (
    "idx_pipeline_jobs_heartbeat_at ON pipeline_jobs(heartbeat_at)",
    "idx_applications_loan_id ON applications(loan_id)",
    "idx_validation_results_status ON validation_results(status)",
    "idx_ocr_route_events_created_at ON ocr_route_events(created_at)",
    "idx_ocr_route_events_event_type ON ocr_route_events(event_type)",
    "idx_audit_log_timestamp ON audit_log(timestamp)",
)


def upgrade() -> None:
    for definition in _INDEXES:
        op.execute(f"CREATE INDEX IF NOT EXISTS {definition}")


def downgrade() -> None:
    for definition in reversed(_INDEXES):
        name = definition.split(" ON ", maxsplit=1)[0]
        op.execute(f"DROP INDEX IF EXISTS {name}")
