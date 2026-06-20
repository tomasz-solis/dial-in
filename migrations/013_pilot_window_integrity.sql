-- Keep pilot phase measurement unambiguous: one baseline and one live window
-- per location. Preserve the newest row if an earlier UI created duplicates.

WITH ranked AS (
    SELECT
        pilot_window_id,
        row_number() OVER (
            PARTITION BY account_id, location_id, phase
            ORDER BY created_at DESC, pilot_window_id DESC
        ) AS row_rank
    FROM pilot_windows
)
DELETE FROM pilot_windows AS window
USING ranked
WHERE window.pilot_window_id = ranked.pilot_window_id
  AND ranked.row_rank > 1;

CREATE UNIQUE INDEX IF NOT EXISTS idx_pilot_windows_unique_phase
    ON pilot_windows(account_id, location_id, phase);
