"""Pages ocr_status column (checklist status-model refactor).

Mirrors the SQLite ``ALTER TABLE pages ADD COLUMN ocr_status TEXT`` in
``database/models.py:MIGRATION_STATEMENTS``. Existing rows become NULL,
which satisfies the CHECK (NULL passes CHECK constraints on both dialects).

Revision ID: 0007_pages_ocr_status
Revises: 0006_user_role
Create Date: 2026-09-10
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007_pages_ocr_status"
down_revision: str | Sequence[str] | None = "0006_user_role"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE pages ADD COLUMN IF NOT EXISTS ocr_status TEXT "
        "CHECK (ocr_status IN ('success', 'failed', 'no_text_extracted', 'not_applicable'))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE pages DROP COLUMN IF EXISTS ocr_status")
