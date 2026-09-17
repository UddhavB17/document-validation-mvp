"""Manual NDC checklist ticks (tmp/user-portal-ux).

One row per application/checklist-row/role; row presence means checked.

Revision ID: 0009_ops_ndc_checks
Revises: 0008_intake_package_error
Create Date: 2026-09-16
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009_ops_ndc_checks"
down_revision: str | Sequence[str] | None = "0008_intake_package_error"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ops_ndc_checks (
            application_id INTEGER NOT NULL REFERENCES applications(id),
            s_no INTEGER NOT NULL,
            role TEXT NOT NULL,
            checked_by INTEGER,
            checked_at TEXT,
            PRIMARY KEY (application_id, s_no, role)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_ops_ndc_checks_application_id "
        "ON ops_ndc_checks(application_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ops_ndc_checks")
