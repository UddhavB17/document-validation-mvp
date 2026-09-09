"""Rename the ``operations`` role to ``user`` (two-role model: admin/user).

Revision ID: 0006_user_role
Revises: 0005_batch_rejections
Create Date: 2026-09-09
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006_user_role"
down_revision: str | Sequence[str] | None = "0005_batch_rejections"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("UPDATE users SET role = 'user' WHERE role = 'operations'")
    bind = op.get_bind()
    if bind is not None and bind.dialect.name == "postgresql":
        # 0004 created an inline CHECK (role IN ('admin', 'operations')).
        # Postgres auto-names it <table>_<column>_check; rebuild it so new
        # 'user' rows pass and stale 'operations' rows are rejected.
        op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check")
        op.execute(
            "ALTER TABLE users ADD CONSTRAINT users_role_check CHECK (role IN ('admin', 'user'))"
        )


def downgrade() -> None:
    op.execute("UPDATE users SET role = 'operations' WHERE role = 'user'")
    bind = op.get_bind()
    if bind is not None and bind.dialect.name == "postgresql":
        op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check")
        op.execute(
            "ALTER TABLE users ADD CONSTRAINT users_role_check "
            "CHECK (role IN ('admin', 'operations'))"
        )
