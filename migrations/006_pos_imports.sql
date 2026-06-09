ALTER TABLE daily_metrics
    DROP CONSTRAINT IF EXISTS daily_metrics_input_source_check;

ALTER TABLE daily_metrics
    ADD CONSTRAINT daily_metrics_input_source_check
    CHECK (input_source IN ('confirmed', 'corrected', 'imputed', 'imported'));

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

CREATE INDEX IF NOT EXISTS idx_pos_import_runs_account_date
    ON pos_import_runs(account_id, location_id, applied_at DESC);

CREATE INDEX IF NOT EXISTS idx_pos_daily_sales_account_date
    ON pos_daily_sales(account_id, location_id, date DESC, category);

ALTER TABLE pos_import_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE pos_import_errors ENABLE ROW LEVEL SECURITY;
ALTER TABLE pos_daily_sales ENABLE ROW LEVEL SECURITY;

ALTER TABLE pos_import_runs FORCE ROW LEVEL SECURITY;
ALTER TABLE pos_import_errors FORCE ROW LEVEL SECURITY;
ALTER TABLE pos_daily_sales FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_pos_import_runs ON pos_import_runs;
CREATE POLICY tenant_pos_import_runs ON pos_import_runs
    USING (account_id = current_setting('app.current_account_id', true))
    WITH CHECK (account_id = current_setting('app.current_account_id', true));

DROP POLICY IF EXISTS tenant_pos_import_errors ON pos_import_errors;
CREATE POLICY tenant_pos_import_errors ON pos_import_errors
    USING (account_id = current_setting('app.current_account_id', true))
    WITH CHECK (account_id = current_setting('app.current_account_id', true));

DROP POLICY IF EXISTS tenant_pos_daily_sales ON pos_daily_sales;
CREATE POLICY tenant_pos_daily_sales ON pos_daily_sales
    USING (account_id = current_setting('app.current_account_id', true))
    WITH CHECK (account_id = current_setting('app.current_account_id', true));

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dialin_app') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON
            pos_import_runs,
            pos_import_errors,
            pos_daily_sales
        TO dialin_app;
    END IF;
END
$$;
