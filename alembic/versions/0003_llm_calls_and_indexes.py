"""llm_calls ok/error columns plus missing indexes (fx-schema).

Adds ``ok``/``error`` to ``llm_calls`` (canonical SQLite DDL lives in
``database/llm_calls.py``) and creates indexes that exist in SQLite but were
missing from the 0001 baseline: ``idx_llm_calls_model``,
``idx_llm_calls_created_at``, ``idx_pipeline_jobs_batch_id``.

Revision ID: 0003_llm_calls_and_indexes
Revises: 0002_worker_heartbeat
Create Date: 2026-09-05
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003_llm_calls_and_indexes"
down_revision: str | Sequence[str] | None = "0002_worker_heartbeat"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE llm_calls ADD COLUMN ok BOOLEAN NOT NULL DEFAULT TRUE"
    )
    op.execute("ALTER TABLE llm_calls ADD COLUMN error TEXT")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_llm_calls_model ON llm_calls(model)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_llm_calls_created_at ON llm_calls(created_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_pipeline_jobs_batch_id "
        "ON pipeline_jobs(batch_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_pipeline_jobs_batch_id")
    op.execute("DROP INDEX IF EXISTS idx_llm_calls_created_at")
    op.execute("DROP INDEX IF EXISTS idx_llm_calls_model")
    op.execute("ALTER TABLE llm_calls DROP COLUMN IF EXISTS error")
    op.execute("ALTER TABLE llm_calls DROP COLUMN IF EXISTS ok")
