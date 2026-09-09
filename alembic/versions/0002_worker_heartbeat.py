"""Worker heartbeat singleton (ws-j deploy + smoke).

Dedicated ``worker_heartbeat`` table: one row (``id = 1``) updated by the
worker loop every 30 s even when idle. ``/health`` prefers this row and
falls back to ``MAX(pipeline_jobs.heartbeat_at)``. Stale = older than
2 minutes (checked in Python, not SQL).

Revision ID: 0002_worker_heartbeat
Revises: 0001_baseline
Create Date: 2026-09-05
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002_worker_heartbeat"
down_revision: str | Sequence[str] | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS worker_heartbeat (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            worker_id TEXT,
            heartbeat_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS worker_heartbeat CASCADE")
