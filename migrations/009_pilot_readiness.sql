-- Pilot readiness (Phased Build Plan Phase 12; PRD sections 14, 14.1).
-- Two small tenant-scoped tables: pilot phase windows (baseline vs live) so
-- measurement can be partitioned honestly, and a pilot setup profile capturing
-- the operational/economic context needed before any value claim. Both are
-- advisory metadata; no recommendation reads from them.

CREATE TABLE IF NOT EXISTS pilot_windows (
    pilot_window_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id text NOT NULL,
    location_id text NOT NULL,
    phase text NOT NULL,
    start_date date NOT NULL,
    end_date date,
    note text,
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (account_id, location_id)
        REFERENCES locations(account_id, location_id)
        ON DELETE CASCADE,
    CHECK (phase IN ('baseline', 'live')),
    CHECK (end_date IS NULL OR end_date >= start_date)
);

CREATE TABLE IF NOT EXISTS pilot_profile (
    account_id text NOT NULL,
    location_id text NOT NULL,
    responses jsonb NOT NULL DEFAULT '{}'::jsonb,
    values_source text NOT NULL DEFAULT 'default',
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, location_id),
    FOREIGN KEY (account_id, location_id)
        REFERENCES locations(account_id, location_id)
        ON DELETE CASCADE,
    CHECK (values_source IN ('default', 'owner_confirmed', 'corrected'))
);

CREATE INDEX IF NOT EXISTS idx_pilot_windows_account_phase
    ON pilot_windows(account_id, location_id, phase, start_date DESC);

ALTER TABLE pilot_windows ENABLE ROW LEVEL SECURITY;
ALTER TABLE pilot_profile ENABLE ROW LEVEL SECURITY;

ALTER TABLE pilot_windows FORCE ROW LEVEL SECURITY;
ALTER TABLE pilot_profile FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_pilot_windows ON pilot_windows;
CREATE POLICY tenant_pilot_windows ON pilot_windows
    USING (account_id = current_setting('app.current_account_id', true))
    WITH CHECK (account_id = current_setting('app.current_account_id', true));

DROP POLICY IF EXISTS tenant_pilot_profile ON pilot_profile;
CREATE POLICY tenant_pilot_profile ON pilot_profile
    USING (account_id = current_setting('app.current_account_id', true))
    WITH CHECK (account_id = current_setting('app.current_account_id', true));

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dialin_app') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON
            pilot_windows,
            pilot_profile
        TO dialin_app;
    END IF;
END
$$;
