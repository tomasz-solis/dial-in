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


def test_forecast_actuals_and_recommendation_audit_schema() -> None:
    """Forecast actuals may be missing and recommendations should be append-only."""

    init_sql = Path("migrations/001_init.sql").read_text(encoding="utf-8")
    migration_sql = Path(
        "migrations/007_forecast_actuals_and_recommendation_audit.sql"
    ).read_text(encoding="utf-8")

    assert "temp_actual numeric(6, 2)," in init_sql
    assert "rain_actual numeric(8, 2)," in init_sql
    assert "actual_observed_at timestamptz" in init_sql
    assert "input_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb" in init_sql
    assert "config_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb" in init_sql
    assert "is_active boolean NOT NULL DEFAULT true" in init_sql
    assert "superseded_by uuid REFERENCES recommendations(recommendation_id)" in init_sql
    assert "WHERE is_active = true" in init_sql

    assert "ALTER COLUMN temp_actual DROP NOT NULL" in migration_sql
    assert "ALTER COLUMN rain_actual DROP NOT NULL" in migration_sql
    assert "ADD COLUMN IF NOT EXISTS actual_observed_at" in migration_sql
    assert (
        "DROP CONSTRAINT IF EXISTS "
        "recommendations_account_id_location_id_date_category_model_version_key"
    ) in migration_sql
    assert "idx_recommendations_active_unique" in migration_sql


def test_init_schema_includes_migration_ledger() -> None:
    """Fresh databases should include a schema migration ledger."""

    init_sql = Path("migrations/001_init.sql").read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS schema_migrations" in init_sql
    assert "filename text PRIMARY KEY" in init_sql


def test_product_integrity_migrations_track_weather_source_and_unique_pilot_phases() -> None:
    init_sql = Path("migrations/001_init.sql").read_text(encoding="utf-8")
    weather_sql = Path("migrations/012_weather_provenance.sql").read_text(encoding="utf-8")
    pilot_sql = Path("migrations/013_pilot_window_integrity.sql").read_text(encoding="utf-8")

    assert "forecast_source text NOT NULL DEFAULT 'legacy'" in init_sql
    assert "forecast_source IN ('legacy', 'synthetic_demo', 'open_meteo')" in init_sql
    assert "ADD COLUMN IF NOT EXISTS forecast_source" in weather_sql
    assert "locations_latitude_check" in weather_sql
    assert "idx_pilot_windows_unique_phase" in pilot_sql


def test_ci_runs_quality_type_test_and_realism_gates() -> None:
    """The default CI workflow should gate the daily-product quality checks."""

    ci_sql = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "uv run ruff check" in ci_sql
    assert "uv run mypy" in ci_sql
    assert "uv run pytest" in ci_sql
    assert "uv run python scripts/generate_synthetic_data.py --seed 20260531" in ci_sql
    assert "uv run python scripts/validate_realism.py data/generated" in ci_sql
    assert "permissions:\n  contents: read" in ci_sql
    assert "timeout-minutes: 15" in ci_sql


def test_scheduled_refresh_is_serialized_and_bounded() -> None:
    workflow = Path(".github/workflows/refresh-demo-data.yml").read_text(encoding="utf-8")

    assert "group: refresh-demo-data" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "permissions:\n  contents: read" in workflow
    assert "timeout-minutes: 15" in workflow
