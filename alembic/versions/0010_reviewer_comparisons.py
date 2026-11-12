"""Persist reviewer comparison outputs at pipeline finalization.

Revision ID: 0010_reviewer_comparisons
Revises: 0009_performance_indexes
Create Date: 2026-11-12
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0010_reviewer_comparisons"
down_revision: str | Sequence[str] | None = "0009_performance_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS reviewer_comparisons (
            application_id BIGINT PRIMARY KEY REFERENCES applications(id),
            pipeline_job_id BIGINT,
            comparison_matrix_json TEXT NOT NULL,
            relationships_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS reviewer_comparisons")
