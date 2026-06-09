ALTER TABLE recommendations
    ADD COLUMN IF NOT EXISTS override_reason text;
