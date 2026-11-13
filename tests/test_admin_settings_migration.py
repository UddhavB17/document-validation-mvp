from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text


def _migration():
    path = (
        Path(__file__).resolve().parents[1] / "alembic/versions/0011_admin_validation_settings.py"
    )
    spec = spec_from_file_location("admin_validation_settings_migration", path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_admin_settings_migration_is_idempotent_and_preserves_existing_values(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE system_settings (config_key TEXT PRIMARY KEY, "
                "config_value TEXT NOT NULL, value_type TEXT NOT NULL, "
                "category TEXT NOT NULL, label TEXT, description TEXT)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO system_settings VALUES "
                "('validation.name_fuzzy_threshold', '91', 'float', 'validation', 'Custom', 'Existing admin value')"
            )
        )
        migration = _migration()
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            migration.upgrade()

        rows = connection.execute(
            text(
                "SELECT config_key, config_value FROM system_settings "
                "WHERE config_key LIKE 'validation.%' ORDER BY config_key"
            )
        ).all()

    assert rows == [
        ("validation.amount_tolerance_percent", "1.0"),
        ("validation.date_tolerance_days", "0"),
        ("validation.name_fuzzy_threshold", "91"),
    ]
    engine.dispose()
