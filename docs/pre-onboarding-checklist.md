# Pre-onboarding checklist: first real-data pilot

An ordered runbook for moving Dial In from honest demo to one real café running it safely on day 1. It turns the work PRD §23 lists as "before a real-data pilot" into checkable steps, each pointing at its PRD section and the code that implements it (or still needs to).

Scope: one tightly managed, single-location, advisory pilot, not multi-tenant self-serve. Every number stays advisory until the §6.4 model gates and the §6.5 value gate clear. The artifact to share in phases 4 and 5 is the pilot report (`src/dialin/pilot_report.py`, downloadable from Performance → Advanced).

Legend: `[ ]` to do · `[~]` partly in place · `[x]` done.

## Phase 0: pre-flight (code hygiene)

- [ ] `uv run ruff check` and `uv run mypy` clean; `uv run pytest` green, including the RLS job in `.github/workflows/ci.yml`.
- [x] Remove dead code. `streamlit_cache._history_frames` duplicated `repository.fetch_history_frames` (only a test referenced it, to assert it wasn't used). Removed (about 70 lines) and the test slice pointed at `_location_hours_plan`.
- [ ] Confirm the demo refresh is not scheduled against the pilot database (`scripts/scheduled_refresh.py`, `.github/workflows/refresh-demo-data.yml`).

## Phase 1: operate safely (blocks charging anyone). PRD §23, §18

Once a café's closeouts are the only copy of its data, none of this is optional.

- [ ] Tested restore drill. Back up the pilot Neon database, restore it into a scratch database, and record the runbook and the measured restore time.
- [ ] Failure alerts to a named owner, each with a one-line runbook:
  - [ ] Failed or delayed daily refresh (`scripts/scheduled_refresh.py`).
  - [ ] Stale or missing weather. The app already degrades through the weather seam; add an out-of-band alert so nobody has to notice it in the UI.
  - [ ] Migration failure (`scripts/migrate.py`).
- [ ] A hard demo vs real guard. Make it impossible for the demo refresh or synthetic truth to run against a real tenant, for example with a per-account `plan` flag that the refresh and the `demo_truth` loader refuse to cross, tested and not just a convention (`accounts.plan`, `src/dialin/demo_truth.py`, `src/dialin/demo_freshness.py`).
- [ ] Confirm the app only runs as the low-privilege `dialin_app` role. The database enforces RLS (`migrations/002_rls.sql`, `db.assert_not_owner_connection`).
- [ ] Acceptance: restore drill recorded; alerts routed; warm p95 Today load under 3s and p95 closeout to recommendation under 5s for 7 operating days in a row; missing closeouts or weather degrade visibly, never silently.

## Phase 2: onboard the location (repeatable setup). PRD §17.1, §15, §1.1

- [ ] Confirm economics as a day-1 blocking gate. Capture real `retail_price`, `unit_cogs`, salvage, attach rate and `service_quantile` so `category_economics.values_source` is no longer `'default'`. Until then the euro headline can't be trusted: the engine lowers confidence on default economics (`engine._downgrade_confidence`) and the readiness panel stays at the setup stage.
- [ ] Real opening hours and closed days (`location_hours`, owner-confirmed `source`), so comparability and prep targets are right.
- [ ] Categories. The engine handles any categories (`build_recommendations` loops over the categories in the data), but the closeout form and the `pos_daily_sales` CHECK are fixed to `sweet/savory/drinks`. For a café with a different menu, category and SKU closeout setup should be a data change, not a code change (PRD §15, §23).
- [ ] Cold-start UX for thin history. A new café hits the `engine._forecast_traffic` fallback of `base=100.0` at Low confidence. Label it clearly as "learning your café, advisory only" for the first weeks instead of a silent anchor. (The pooled `shared_environment.cold_start_prior` exists but is unfitted on purpose.)
- [ ] Repeatable POS onboarding: reusable column mappings with re-import and reconciliation, and audited import failures (`pos_import_runs`, `pos_import_errors`, `src/dialin/pos_import.py`).
- [ ] Set the pilot baseline and live windows and finish the setup checklist on the Setup tab (`repository.pilot`, `pilot_windows` / `pilot_profile`).

## Phase 3: first operating week (show progress, not a blank scoreboard). PRD §6.3, §6.5

- [x] Data-readiness panel. The owner summary shows "Getting to a verdict" progress before a verdict exists: economics confirmed, clean closeouts, 28 clean open days, recommendation used, value verdict (`metrics.onboarding_readiness`, `views/performance._render_readiness`).
- [ ] Closeout discipline. Keep `missing_closeout_rate` low, and record sellout times and override reasons so attribution and de-censoring stay honest.
- [ ] Watch the operations-health strip (missing closeouts, POS rejects, suspicious jumps) in Advanced analysis (`metrics.daily_operations_health`, `metrics.suspicious_operational_jumps`).

## Phase 4: prove the decision on real data. PRD §6.4, §12

- [ ] Run a shadow window at the real café, with recommendations frozen before the outcome (`recommendations.input_snapshot` and `config_snapshot` are already stored per row).
- [ ] Compare Tobit and comparable-day de-censoring against both naive baselines on the same held-out dates (`censoring.tobit_decensored_demand`, `engine.decensored_demand_series`, `metrics.evaluate_model_vs_baselines`).
- [ ] Nothing drives prep until the per-category gates clear (`metrics.model_gate_report`: at least 28 evaluated days, calibrated coverage, low censoring, unbiased, beats both baselines, and a robust expected-cost gain). Categories stay `shadow` until then.

## Phase 5: prove value and decide whether they'd pay again. PRD §6.5

- [ ] Report the §6.5 value gate honestly and all together: waste proxy, sellout frequency, expected mis-prep cost with its 95% interval (`metrics.expected_misprep_cost`, `savings_robust`) and adherence. The owner summary is the commercial view; Advanced analysis is the audit trail behind it.
- [ ] Generate and share the pilot report (`pilot_report.build_pilot_report_markdown`): observed, estimated, assumed and not claimed, with no validated ROI claim.
- [ ] Answer the question that decides whether it can be sold: would the owner keep paying?

> Staffing, ingredients, inventory and cross-location benchmarks stay out of scope until a real café clears both the model gate and the pay-again gate (PRD §23).
