"""Intake package failure reason (surfaces ZIP validation errors in the UI).

Without this, a failed background preparation deletes its staging dir and
leaves no row behind, so polling degrades to an unexplained 404. Failed
preparations now persist a row with ``status = 'failed'`` and the error
text, which ``GET /upload/package/{id}/preparation`` returns directly.

Revision ID: 0008_intake_package_error
Revises: 0007_pages_ocr_status
Create Date: 2026-09-10
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008_intake_package_error"
down_revision: str | Sequence[str] | None = "0007_pages_ocr_status"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE intake_packages ADD COLUMN IF NOT EXISTS error TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE intake_packages DROP COLUMN IF EXISTS error")
