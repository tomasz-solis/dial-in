ALTER TABLE category_economics
    ADD COLUMN IF NOT EXISTS values_source text NOT NULL DEFAULT 'default';

DO $$
BEGIN
    ALTER TABLE category_economics
        ADD CONSTRAINT category_economics_values_source_check
        CHECK (values_source IN ('default', 'owner_confirmed', 'corrected'));
EXCEPTION
    WHEN duplicate_object THEN NULL;
END
$$;
