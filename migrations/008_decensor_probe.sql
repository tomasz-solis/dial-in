-- De-censoring probe (PRD section 12, assumption 12).
-- Records when a recommendation deliberately prepped above the owner's service
-- quantile to learn the true demand ceiling, and the per-account opt-in that
-- gates the behaviour. Probing is off by default so existing tenants are unchanged.

ALTER TABLE recommendations
    ADD COLUMN IF NOT EXISTS probe_active boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS probe_extra_units integer NOT NULL DEFAULT 0
        CHECK (probe_extra_units >= 0);

ALTER TABLE accounts
    ADD COLUMN IF NOT EXISTS decensor_probe_opt_in boolean NOT NULL DEFAULT false;
