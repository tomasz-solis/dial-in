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

CREATE INDEX IF NOT EXISTS idx_location_hours_effective
    ON location_hours(account_id, location_id, day_of_week, effective_from DESC);

INSERT INTO location_hours (
    account_id,
    location_id,
    day_of_week,
    is_open,
    open_time,
    close_time,
    effective_from,
    source
)
SELECT
    l.account_id,
    l.location_id,
    day_of_week,
    day_of_week = ANY(l.open_days),
    CASE WHEN day_of_week = ANY(l.open_days) THEN time '08:00' ELSE NULL END,
    CASE WHEN day_of_week = ANY(l.open_days) THEN time '16:00' ELSE NULL END,
    date '2024-01-01',
    'demo_seed'
FROM locations l
CROSS JOIN generate_series(0, 6) AS day_of_week
ON CONFLICT (account_id, location_id, day_of_week, effective_from) DO NOTHING;

ALTER TABLE location_hours ENABLE ROW LEVEL SECURITY;
ALTER TABLE location_hours FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_location_hours ON location_hours;
CREATE POLICY tenant_location_hours ON location_hours
    USING (account_id = current_setting('app.current_account_id', true))
    WITH CHECK (account_id = current_setting('app.current_account_id', true));

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dialin_app') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON location_hours TO dialin_app;
    END IF;
END
$$;
