-- Product-integrity constraints for weather location and provenance.

ALTER TABLE weather
    ADD COLUMN IF NOT EXISTS forecast_source text NOT NULL DEFAULT 'legacy';

ALTER TABLE weather
    DROP CONSTRAINT IF EXISTS weather_forecast_source_check;

ALTER TABLE weather
    ADD CONSTRAINT weather_forecast_source_check
    CHECK (forecast_source IN ('legacy', 'synthetic_demo', 'open_meteo'));

ALTER TABLE locations
    DROP CONSTRAINT IF EXISTS locations_latitude_check,
    DROP CONSTRAINT IF EXISTS locations_longitude_check;

ALTER TABLE locations
    ADD CONSTRAINT locations_latitude_check
        CHECK (latitude IS NULL OR latitude BETWEEN -90 AND 90),
    ADD CONSTRAINT locations_longitude_check
        CHECK (longitude IS NULL OR longitude BETWEEN -180 AND 180);
