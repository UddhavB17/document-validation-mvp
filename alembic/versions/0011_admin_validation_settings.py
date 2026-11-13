"""Seed admin-editable validation settings on PostgreSQL.

Revision ID: 0011_admin_validation_settings
Revises: 0010_reviewer_comparisons
Create Date: 2026-11-13
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0011_admin_validation_settings"
down_revision: str | Sequence[str] | None = "0010_reviewer_comparisons"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SETTINGS = (
    (
        "validation.name_fuzzy_threshold",
        "85",
        "float",
        "validation",
        "Fuzzy Name Match Threshold",
        "Minimum name similarity score required to consider field values equivalent.",
    ),
    (
        "validation.amount_tolerance_percent",
        "1.0",
        "float",
        "validation",
        "Amount Difference Tolerance",
        "Maximum percentage difference allowed when comparing loan amounts.",
    ),
    (
        "validation.date_tolerance_days",
        "0",
        "int",
        "validation",
        "Date Discrepancy Tolerance",
        "Maximum number of days allowed between comparable dates.",
    ),
)


def upgrade() -> None:
    for key, value, value_type, category, label, description in _SETTINGS:
        op.execute(
            """
            INSERT INTO system_settings
                (config_key, config_value, value_type, category, label, description)
            VALUES
                ('{}', '{}', '{}', '{}', '{}', '{}')
            ON CONFLICT (config_key) DO NOTHING
            """.format(key, value, value_type, category, label, description.replace("'", "''"))
        )


def downgrade() -> None:
    # These rows may have been changed by admins after deployment. Preserve
    # their values when rolling back application code.
    pass
