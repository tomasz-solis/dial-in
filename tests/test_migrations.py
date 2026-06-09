"""Static checks for the Postgres tenant-isolation migrations."""

from __future__ import annotations

from pathlib import Path


def test_rls_migration_enables_policies_for_tenant_tables() -> None:
    """The RLS migration should use the account GUC on tenant tables."""

    sql = Path("migrations/002_rls.sql").read_text(encoding="utf-8")

    assert "ENABLE ROW LEVEL SECURITY" in sql
    assert "current_setting('app.current_account_id', true)" in sql
    assert "CREATE POLICY tenant_daily_metrics" in sql
    assert "CREATE POLICY tenant_recommendations" in sql
    assert "GRANT SELECT ON shared_layer_features TO dialin_app" not in sql


def test_recommendations_schema_tracks_override_reason() -> None:
    """Recommendation attribution should include an optional override reason."""

    init_sql = Path("migrations/001_init.sql").read_text(encoding="utf-8")
    migration_sql = Path("migrations/003_recommendation_override_reason.sql").read_text(
        encoding="utf-8"
    )

    assert "override_reason text" in init_sql
    assert "ADD COLUMN IF NOT EXISTS override_reason text" in migration_sql


def test_category_economics_tracks_value_source() -> None:
    """Category economics should distinguish defaults from owner-confirmed values."""

    init_sql = Path("migrations/001_init.sql").read_text(encoding="utf-8")
    migration_sql = Path("migrations/004_category_economics_values_source.sql").read_text(
        encoding="utf-8"
    )

    assert "values_source text NOT NULL DEFAULT 'default'" in init_sql
    assert "owner_confirmed" in init_sql
    assert "ADD COLUMN IF NOT EXISTS values_source" in migration_sql


def test_location_hours_schema_is_tenant_scoped() -> None:
    """Opening hours should be effective-dated and protected by tenant RLS."""

    init_sql = Path("migrations/001_init.sql").read_text(encoding="utf-8")
    rls_sql = Path("migrations/002_rls.sql").read_text(encoding="utf-8")
    migration_sql = Path("migrations/005_location_hours.sql").read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS location_hours" in init_sql
    assert "PRIMARY KEY (account_id, location_id, day_of_week, effective_from)" in init_sql
    assert "CREATE POLICY tenant_location_hours" in rls_sql
    assert "INSERT INTO location_hours" in migration_sql


def test_pos_import_schema_is_tenant_scoped() -> None:
    """POS imports should store run summaries, errors, and rollups behind RLS."""

    init_sql = Path("migrations/001_init.sql").read_text(encoding="utf-8")
    rls_sql = Path("migrations/002_rls.sql").read_text(encoding="utf-8")
    migration_sql = Path("migrations/006_pos_imports.sql").read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS pos_import_runs" in init_sql
    assert "CREATE TABLE IF NOT EXISTS pos_import_errors" in init_sql
    assert "CREATE TABLE IF NOT EXISTS pos_daily_sales" in init_sql
    assert "imported" in init_sql
    assert "CREATE POLICY tenant_pos_import_runs" in rls_sql
    assert "CREATE POLICY tenant_pos_daily_sales" in rls_sql
    assert "daily_metrics_input_source_check" in migration_sql
