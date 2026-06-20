-- Real-weather integration (PRD section 1.1 production to-do).
-- A real forecast provider (Open-Meteo) is queried per site, so each location
-- needs coordinates. Nullable so existing rows are unaffected; the synthetic
-- demo seeds the real coordinates of each café's city, and a location without
-- coordinates simply has no real forecast fetched (seasonal-normal fallback).

ALTER TABLE locations
    ADD COLUMN IF NOT EXISTS latitude numeric(8, 5),
    ADD COLUMN IF NOT EXISTS longitude numeric(8, 5);
