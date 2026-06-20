CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS schema_migrations (
    filename text PRIMARY KEY,
    checksum text NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS accounts (
    account_id text PRIMARY KEY,
    name text NOT NULL,
    plan text NOT NULL DEFAULT 'demo',
    contributes_to_shared_layer boolean NOT NULL DEFAULT true,
    cold_start_pool_opt_in boolean NOT NULL DEFAULT false,
    pos_backfill_months integer NOT NULL DEFAULT 18 CHECK (pos_backfill_months >= 0),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS account_members (
    auth_subject text PRIMARY KEY,
    account_id text NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS locations (
    account_id text NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
    location_id text NOT NULL,
    name text NOT NULL,
    timezone text NOT NULL,
    city text NOT NULL,
    country text NOT NULL,
    open_days integer[] NOT NULL,
    service_capacity_hint integer,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, location_id),
    CHECK (service_capacity_hint IS NULL OR service_capacity_hint > 0)
);

CREATE TABLE IF NOT EXISTS location_hours (
    account_id text NOT NULL,
    location_id text NOT NULL,
    day_of_week integer NOT NULL,
    is_open boolean NOT NULL,
    open_time time,
    close_time time,
    effective_from date NOT NULL,
    effective_to date,
    source text NOT NULL DEFAULT 'demo_seed',
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, location_id, day_of_week, effective_from),
    FOREIGN KEY (account_id, location_id)
        REFERENCES locations(account_id, location_id)
        ON DELETE CASCADE,
    CHECK (day_of_week BETWEEN 0 AND 6),
    CHECK (
        (is_open = false AND open_time IS NULL AND close_time IS NULL)
        OR (is_open = true AND open_time IS NOT NULL AND close_time IS NOT NULL)
    ),
    CHECK (close_time IS NULL OR open_time IS NULL OR close_time > open_time),
    CHECK (effective_to IS NULL OR effective_to > effective_from),
    CHECK (source IN ('demo_seed', 'owner_confirmed', 'corrected'))
);

CREATE TABLE IF NOT EXISTS daily_metrics (
    account_id text NOT NULL,
    location_id text NOT NULL,
    date date NOT NULL,
    timezone text NOT NULL,
    is_open boolean NOT NULL,
    drinks_sold integer,
    input_source text NOT NULL DEFAULT 'confirmed',
    menu_version text NOT NULL DEFAULT 'v1',
    recorded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, location_id, date),
    FOREIGN KEY (account_id, location_id)
        REFERENCES locations(account_id, location_id)
        ON DELETE CASCADE,
    CHECK (drinks_sold IS NULL OR drinks_sold >= 0),
    CHECK (input_source IN ('confirmed', 'corrected', 'imputed', 'imported'))
);

CREATE TABLE IF NOT EXISTS daily_category_metrics (
    account_id text NOT NULL,
    location_id text NOT NULL,
    date date NOT NULL,
    category text NOT NULL,
    sold integer NOT NULL,
    prepared integer NOT NULL,
    sold_out boolean NOT NULL,
    stockout_detected_by text NOT NULL DEFAULT 'inferred_cap',
    time_last_sale timestamptz,
    salvage_share_observed numeric(6, 4),
    input_source text NOT NULL DEFAULT 'confirmed',
    PRIMARY KEY (account_id, location_id, date, category),
    FOREIGN KEY (account_id, location_id, date)
        REFERENCES daily_metrics(account_id, location_id, date)
        ON DELETE CASCADE,
    CHECK (sold >= 0),
    CHECK (prepared >= 0),
    CHECK (sold <= prepared),
    CHECK (salvage_share_observed IS NULL OR salvage_share_observed BETWEEN 0 AND 1),
    CHECK (stockout_detected_by IN ('inferred_cap', 'pos_out_of_stock', 'manual', 'unknown')),
    CHECK (input_source IN ('confirmed', 'corrected', 'imputed'))
);

CREATE TABLE IF NOT EXISTS weather (
    account_id text NOT NULL,
    location_id text NOT NULL,
    date date NOT NULL,
    temp_forecast numeric(6, 2) NOT NULL,
    temp_actual numeric(6, 2),
    rain_forecast numeric(8, 2) NOT NULL,
    rain_actual numeric(8, 2),
    wind numeric(6, 2) NOT NULL,
    condition text NOT NULL,
    forecast_source text NOT NULL DEFAULT 'legacy',
    forecast_made_at timestamptz NOT NULL,
    actual_observed_at timestamptz,
    PRIMARY KEY (account_id, location_id, date),
    FOREIGN KEY (account_id, location_id)
        REFERENCES locations(account_id, location_id)
        ON DELETE CASCADE,
    CHECK (rain_forecast >= 0),
    CHECK (rain_actual >= 0),
    CHECK (wind >= 0),
    CHECK (forecast_source IN ('legacy', 'synthetic_demo', 'open_meteo'))
);

CREATE TABLE IF NOT EXISTS events (
    event_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id text NOT NULL,
    location_id text NOT NULL,
    date date NOT NULL,
    event_name text NOT NULL,
    event_type text NOT NULL,
    impact_score numeric(6, 4) NOT NULL,
    source text NOT NULL,
    confidence text NOT NULL,
    FOREIGN KEY (account_id, location_id)
        REFERENCES locations(account_id, location_id)
        ON DELETE CASCADE,
    CHECK (impact_score >= 0),
    CHECK (confidence IN ('Low', 'Medium', 'High'))
);

CREATE TABLE IF NOT EXISTS category_economics (
    account_id text NOT NULL,
    location_id text NOT NULL,
    category text NOT NULL,
    retail_price numeric(8, 2) NOT NULL,
    unit_cogs numeric(8, 2) NOT NULL,
    salvage_share_default numeric(6, 4) NOT NULL DEFAULT 0,
    attached_drink_margin numeric(8, 2) NOT NULL DEFAULT 0,
    attach_and_balk_rate numeric(6, 4) NOT NULL DEFAULT 0,
    service_quantile numeric(6, 4) NOT NULL,
    values_source text NOT NULL DEFAULT 'default',
    effective_from date NOT NULL,
    effective_to date,
    PRIMARY KEY (account_id, location_id, category, effective_from),
    FOREIGN KEY (account_id, location_id)
        REFERENCES locations(account_id, location_id)
        ON DELETE CASCADE,
    CHECK (retail_price >= 0),
    CHECK (unit_cogs >= 0),
    CHECK (salvage_share_default BETWEEN 0 AND 1),
    CHECK (attach_and_balk_rate BETWEEN 0 AND 1),
    CHECK (service_quantile > 0 AND service_quantile < 1),
    CHECK (values_source IN ('default', 'owner_confirmed', 'corrected')),
    CHECK (effective_to IS NULL OR effective_to > effective_from)
);

CREATE TABLE IF NOT EXISTS recommendations (
    recommendation_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id text NOT NULL,
    location_id text NOT NULL,
    date date NOT NULL,
    category text NOT NULL,
    recommended_prep integer NOT NULL,
    demand_p50 integer NOT NULL,
    demand_p_lower integer NOT NULL,
    demand_p_upper integer NOT NULL,
    service_quantile numeric(6, 4) NOT NULL,
    prepared integer,
    adhered boolean,
    override_delta integer,
    override_reason text,
    confidence text NOT NULL,
    risk_flag text NOT NULL,
    top_drivers jsonb NOT NULL DEFAULT '[]'::jsonb,
    model_version text NOT NULL,
    input_snapshot_id text NOT NULL,
    config_snapshot_id text NOT NULL,
    input_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
    config_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
    is_active boolean NOT NULL DEFAULT true,
    superseded_at timestamptz,
    superseded_by uuid REFERENCES recommendations(recommendation_id),
    generated_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (account_id, location_id)
        REFERENCES locations(account_id, location_id)
        ON DELETE CASCADE,
    CHECK (recommended_prep >= 0),
    CHECK (demand_p50 >= 0),
    CHECK (demand_p_lower >= 0),
    CHECK (demand_p_upper >= demand_p_lower),
    CHECK (prepared IS NULL OR prepared >= 0),
    CHECK (confidence IN ('Low', 'Medium', 'High')),
    CHECK (service_quantile > 0 AND service_quantile < 1)
);

CREATE TABLE IF NOT EXISTS data_corrections (
    correction_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id text NOT NULL,
    location_id text NOT NULL,
    date date NOT NULL,
    category text,
    field_name text NOT NULL,
    old_value text,
    new_value text,
    corrected_by text NOT NULL,
    corrected_at timestamptz NOT NULL DEFAULT now(),
    reason text,
    FOREIGN KEY (account_id, location_id)
        REFERENCES locations(account_id, location_id)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS pos_import_runs (
    import_run_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id text NOT NULL,
    location_id text NOT NULL,
    filename text NOT NULL,
    created_by text NOT NULL,
    date_start date,
    date_end date,
    rows_read integer NOT NULL,
    rows_imported integer NOT NULL,
    rows_rejected integer NOT NULL,
    timestamp_coverage numeric(6, 4) NOT NULL,
    mapping_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    applied_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (account_id, location_id)
        REFERENCES locations(account_id, location_id)
        ON DELETE CASCADE,
    CHECK (date_start IS NULL OR date_end IS NULL OR date_end >= date_start),
    CHECK (rows_read >= 0),
    CHECK (rows_imported >= 0),
    CHECK (rows_rejected >= 0),
    CHECK (timestamp_coverage BETWEEN 0 AND 1)
);

CREATE TABLE IF NOT EXISTS pos_import_errors (
    error_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    import_run_id uuid NOT NULL REFERENCES pos_import_runs(import_run_id) ON DELETE CASCADE,
    account_id text NOT NULL,
    location_id text NOT NULL,
    row_number integer NOT NULL,
    reason text NOT NULL,
    raw_row jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (account_id, location_id)
        REFERENCES locations(account_id, location_id)
        ON DELETE CASCADE,
    CHECK (row_number > 0)
);

CREATE TABLE IF NOT EXISTS pos_daily_sales (
    account_id text NOT NULL,
    location_id text NOT NULL,
    date date NOT NULL,
    category text NOT NULL,
    units_sold integer NOT NULL,
    first_sale_at timestamptz,
    last_sale_at timestamptz,
    import_run_id uuid NOT NULL REFERENCES pos_import_runs(import_run_id),
    imported_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, location_id, date, category),
    FOREIGN KEY (account_id, location_id)
        REFERENCES locations(account_id, location_id)
        ON DELETE CASCADE,
    CHECK (category IN ('drinks', 'sweet', 'savory')),
    CHECK (units_sold >= 0),
    CHECK (last_sale_at IS NULL OR first_sale_at IS NULL OR last_sale_at >= first_sale_at)
);

CREATE OR REPLACE VIEW shared_layer_features AS
SELECT
    l.city,
    l.country,
    d.date,
    avg(d.drinks_sold) AS avg_drinks_sold,
    avg(w.temp_actual) AS avg_temp_actual,
    avg(w.rain_actual) AS avg_rain_actual,
    count(*) AS contributing_location_days
FROM daily_metrics d
JOIN accounts a ON a.account_id = d.account_id
JOIN locations l ON l.account_id = d.account_id AND l.location_id = d.location_id
LEFT JOIN weather w ON w.account_id = d.account_id
    AND w.location_id = d.location_id
    AND w.date = d.date
WHERE a.contributes_to_shared_layer = true
  AND d.is_open = true
GROUP BY l.city, l.country, d.date;

CREATE INDEX IF NOT EXISTS idx_daily_metrics_account_date
    ON daily_metrics(account_id, location_id, date DESC);

CREATE INDEX IF NOT EXISTS idx_location_hours_effective
    ON location_hours(account_id, location_id, day_of_week, effective_from DESC);

CREATE INDEX IF NOT EXISTS idx_daily_category_account_date
    ON daily_category_metrics(account_id, location_id, category, date DESC);

CREATE INDEX IF NOT EXISTS idx_recommendations_account_date
    ON recommendations(account_id, location_id, date DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_recommendations_active_unique
    ON recommendations(account_id, location_id, date, category, model_version)
    WHERE is_active = true;

CREATE INDEX IF NOT EXISTS idx_pos_import_runs_account_date
    ON pos_import_runs(account_id, location_id, applied_at DESC);

CREATE INDEX IF NOT EXISTS idx_pos_daily_sales_account_date
    ON pos_daily_sales(account_id, location_id, date DESC, category);

CREATE INDEX IF NOT EXISTS idx_events_account_date
    ON events(account_id, location_id, date);
