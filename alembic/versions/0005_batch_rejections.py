"""Batch rejections table (fx-hygiene).

Postgres does not run ``database/db.py:init_db()`` when ``DATABASE_URL`` is
set, so the ``batch_rejections`` table registered by
``database/batch_rejections.py`` needs a migration. Mirrors the SQLite DDL
(dialect-neutral TEXT PK ``id``, ``batch_id``, ``filename``, ``reason``,
``created_at``, index on ``batch_id``).

Revision ID: 0005_batch_rejections
Revises: 0004_auth_users
Create Date: 2026-09-05
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005_batch_rejections"
down_revision: str | Sequence[str] | None = "0004_auth_users"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS batch_rejections (
            id TEXT PRIMARY KEY,
            batch_id TEXT NOT NULL,
            filename TEXT NOT NULL,
            reason TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_batch_rejections_batch "
        "ON batch_rejections(batch_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_batch_rejections_batch")
    op.execute("DROP TABLE IF EXISTS batch_rejections")
