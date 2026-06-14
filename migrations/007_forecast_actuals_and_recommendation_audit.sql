ALTER TABLE weather
    ALTER COLUMN temp_actual DROP NOT NULL,
    ALTER COLUMN rain_actual DROP NOT NULL;

ALTER TABLE weather
    ADD COLUMN IF NOT EXISTS actual_observed_at timestamptz;

ALTER TABLE recommendations
    ADD COLUMN IF NOT EXISTS input_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS config_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS is_active boolean NOT NULL DEFAULT true,
    ADD COLUMN IF NOT EXISTS superseded_at timestamptz,
    ADD COLUMN IF NOT EXISTS superseded_by uuid REFERENCES recommendations(recommendation_id);

ALTER TABLE recommendations
    DROP CONSTRAINT IF EXISTS recommendations_account_id_location_id_date_category_model_version_key;

CREATE UNIQUE INDEX IF NOT EXISTS idx_recommendations_active_unique
    ON recommendations(account_id, location_id, date, category, model_version)
    WHERE is_active = true;
