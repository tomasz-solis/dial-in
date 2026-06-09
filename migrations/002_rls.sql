ALTER TABLE accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE account_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE locations ENABLE ROW LEVEL SECURITY;
ALTER TABLE location_hours ENABLE ROW LEVEL SECURITY;
ALTER TABLE daily_metrics ENABLE ROW LEVEL SECURITY;
ALTER TABLE daily_category_metrics ENABLE ROW LEVEL SECURITY;
ALTER TABLE weather ENABLE ROW LEVEL SECURITY;
ALTER TABLE events ENABLE ROW LEVEL SECURITY;
ALTER TABLE category_economics ENABLE ROW LEVEL SECURITY;
ALTER TABLE recommendations ENABLE ROW LEVEL SECURITY;
ALTER TABLE data_corrections ENABLE ROW LEVEL SECURITY;
ALTER TABLE pos_import_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE pos_import_errors ENABLE ROW LEVEL SECURITY;
ALTER TABLE pos_daily_sales ENABLE ROW LEVEL SECURITY;

ALTER TABLE accounts FORCE ROW LEVEL SECURITY;
ALTER TABLE account_members FORCE ROW LEVEL SECURITY;
ALTER TABLE locations FORCE ROW LEVEL SECURITY;
ALTER TABLE location_hours FORCE ROW LEVEL SECURITY;
ALTER TABLE daily_metrics FORCE ROW LEVEL SECURITY;
ALTER TABLE daily_category_metrics FORCE ROW LEVEL SECURITY;
ALTER TABLE weather FORCE ROW LEVEL SECURITY;
ALTER TABLE events FORCE ROW LEVEL SECURITY;
ALTER TABLE category_economics FORCE ROW LEVEL SECURITY;
ALTER TABLE recommendations FORCE ROW LEVEL SECURITY;
ALTER TABLE data_corrections FORCE ROW LEVEL SECURITY;
ALTER TABLE pos_import_runs FORCE ROW LEVEL SECURITY;
ALTER TABLE pos_import_errors FORCE ROW LEVEL SECURITY;
ALTER TABLE pos_daily_sales FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_accounts ON accounts;
CREATE POLICY tenant_accounts ON accounts
    USING (account_id = current_setting('app.current_account_id', true))
    WITH CHECK (account_id = current_setting('app.current_account_id', true));

DROP POLICY IF EXISTS tenant_account_members ON account_members;
CREATE POLICY tenant_account_members ON account_members
    USING (account_id = current_setting('app.current_account_id', true))
    WITH CHECK (account_id = current_setting('app.current_account_id', true));

DROP POLICY IF EXISTS tenant_locations ON locations;
CREATE POLICY tenant_locations ON locations
    USING (account_id = current_setting('app.current_account_id', true))
    WITH CHECK (account_id = current_setting('app.current_account_id', true));

DROP POLICY IF EXISTS tenant_location_hours ON location_hours;
CREATE POLICY tenant_location_hours ON location_hours
    USING (account_id = current_setting('app.current_account_id', true))
    WITH CHECK (account_id = current_setting('app.current_account_id', true));

DROP POLICY IF EXISTS tenant_daily_metrics ON daily_metrics;
CREATE POLICY tenant_daily_metrics ON daily_metrics
    USING (account_id = current_setting('app.current_account_id', true))
    WITH CHECK (account_id = current_setting('app.current_account_id', true));

DROP POLICY IF EXISTS tenant_daily_category_metrics ON daily_category_metrics;
CREATE POLICY tenant_daily_category_metrics ON daily_category_metrics
    USING (account_id = current_setting('app.current_account_id', true))
    WITH CHECK (account_id = current_setting('app.current_account_id', true));

DROP POLICY IF EXISTS tenant_weather ON weather;
CREATE POLICY tenant_weather ON weather
    USING (account_id = current_setting('app.current_account_id', true))
    WITH CHECK (account_id = current_setting('app.current_account_id', true));

DROP POLICY IF EXISTS tenant_events ON events;
CREATE POLICY tenant_events ON events
    USING (account_id = current_setting('app.current_account_id', true))
    WITH CHECK (account_id = current_setting('app.current_account_id', true));

DROP POLICY IF EXISTS tenant_category_economics ON category_economics;
CREATE POLICY tenant_category_economics ON category_economics
    USING (account_id = current_setting('app.current_account_id', true))
    WITH CHECK (account_id = current_setting('app.current_account_id', true));

DROP POLICY IF EXISTS tenant_recommendations ON recommendations;
CREATE POLICY tenant_recommendations ON recommendations
    USING (account_id = current_setting('app.current_account_id', true))
    WITH CHECK (account_id = current_setting('app.current_account_id', true));

DROP POLICY IF EXISTS tenant_data_corrections ON data_corrections;
CREATE POLICY tenant_data_corrections ON data_corrections
    USING (account_id = current_setting('app.current_account_id', true))
    WITH CHECK (account_id = current_setting('app.current_account_id', true));

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
        GRANT USAGE ON SCHEMA public TO dialin_app;
        GRANT SELECT, INSERT, UPDATE, DELETE ON
            accounts,
            account_members,
            locations,
            location_hours,
            daily_metrics,
            daily_category_metrics,
            weather,
            events,
            category_economics,
            recommendations,
            data_corrections,
            pos_import_runs,
            pos_import_errors,
            pos_daily_sales
        TO dialin_app;
    END IF;
END
$$;
