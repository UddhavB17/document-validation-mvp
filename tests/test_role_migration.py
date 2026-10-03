"""Role migrations must work on populated PostgreSQL tables in both directions."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from database.db import _get_engine, dialect


@pytest.mark.parametrize(
    ("direction", "before", "after"),
    [("upgrade", "operations", "user"), ("downgrade", "user", "operations")],
)
def test_role_migration_preserves_users_and_rebuilds_constraint(direction, before, after):
    if dialect() != "postgresql":
        pytest.skip("Role constraint migration requires PostgreSQL")
    spec = spec_from_file_location(
        "role_migration", Path(__file__).resolve().parents[1] / "alembic/versions/0006_user_role.py"
    )
    assert spec is not None and spec.loader is not None
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    with _get_engine().begin() as connection:
        # A temporary table shadows the real users table for this connection.
        connection.execute(
            text(
                "CREATE TEMPORARY TABLE users (email TEXT, role TEXT "
                f"CHECK (role IN ('admin', '{before}'))) ON COMMIT DROP"
            )
        )
        connection.execute(
            text(
                "INSERT INTO users VALUES ('admin@example.test', 'admin'), "
                "('reviewer@example.test', :role)"
            ),
            {"role": before},
        )
        with Operations.context(MigrationContext.configure(connection)):
            getattr(migration, direction)()
        assert connection.execute(
            text("SELECT role FROM users ORDER BY email")
        ).scalars().all() == [
            "admin",
            after,
        ]
        with pytest.raises(IntegrityError), connection.begin_nested():
            connection.execute(
                text("INSERT INTO users VALUES ('invalid@example.test', :role)"), {"role": before}
            )
