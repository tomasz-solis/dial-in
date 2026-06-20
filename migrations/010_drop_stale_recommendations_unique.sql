-- Fix for migration 007: the DROP CONSTRAINT there named the old unique
-- constraint by its untruncated name, which never matched Postgres's 63-char
-- truncated auto-name, so the stale constraint
-- UNIQUE (account_id, location_id, date, category, model_version) survived on
-- every environment. It has no is_active condition, so it blocks the append-only
-- supersede-then-insert flow (a second, even superseded, row for the same key
-- fails). Uniqueness for *active* rows is already enforced by the partial index
-- idx_recommendations_active_unique created in 007. Drop whatever table-level
-- UNIQUE constraint remains, regardless of its exact (possibly truncated) name.

DO $$
DECLARE
    target_conname text;
BEGIN
    SELECT conname INTO target_conname
    FROM pg_constraint
    WHERE conrelid = 'recommendations'::regclass
      AND contype = 'u'
      AND (
          SELECT array_agg(attribute.attname ORDER BY key.ordinality)
          FROM unnest(conkey) WITH ORDINALITY AS key(attnum, ordinality)
          JOIN pg_attribute AS attribute
            ON attribute.attrelid = conrelid
           AND attribute.attnum = key.attnum
      ) = ARRAY['account_id', 'location_id', 'date', 'category', 'model_version'];
    IF target_conname IS NOT NULL THEN
        EXECUTE format('ALTER TABLE recommendations DROP CONSTRAINT %I', target_conname);
    END IF;
END
$$;
