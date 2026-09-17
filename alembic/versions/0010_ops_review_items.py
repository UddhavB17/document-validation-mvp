"""Persisted human review state for individual operations findings."""

from collections.abc import Sequence

from alembic import op

revision: str = "0010_ops_review_items"
down_revision: str | Sequence[str] | None = "0009_ops_ndc_checks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ops_review_items (
            item_id TEXT PRIMARY KEY,
            application_id INTEGER NOT NULL REFERENCES applications(id),
            validation_result_id INTEGER NOT NULL REFERENCES validation_results(id),
            finding_revision TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'reviewed')),
            disposition TEXT CHECK(disposition IN ('correct', 'reopen')),
            reviewer_id INTEGER REFERENCES users(id),
            reviewed_at TEXT,
            note TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(application_id, validation_result_id, finding_revision)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_ops_review_items_application_id "
        "ON ops_review_items(application_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_ops_review_items_application_status "
        "ON ops_review_items(application_id, status)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ops_review_items")
