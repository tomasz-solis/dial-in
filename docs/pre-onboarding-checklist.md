# Pre-onboarding checklist — first real-data pilot

A sequenced runbook for taking Dial In from "honest demo" to "one real café running it
safely on day 1." It collects the operational and onboarding work that PRD §23 lists as
*before a real-data pilot* into ordered, checkable steps, each pointing at the PRD section and
the code that implements (or still needs) it.

**Scope:** one tightly-managed, single-location, advisory pilot — not multi-tenant self-serve.
Keep every number advisory until the §6.4 model gates and the §6.5 value gate clear. The
shareable artifact for phases 4–5 is the pilot report (`src/dialin/pilot_report.py`,
downloadable from Performance → Advanced).

Legend: `[ ]` to do · `[~]` partially in place · `[x]` done.

---

## Phase 0 — Pre-flight (code hygiene)

- [ ] `uv run ruff check` and `uv run mypy` clean; `uv run pytest` green (incl. the RLS job in
      `.github/workflows/ci.yml`).
- [x] Delete dead code: `streamlit_cache._history_frames` was a stale duplicate of
      `repository.fetch_history_frames` (only a test referenced it to assert non-use). Removed (~70
      lines) and the test slice repointed to `_location_hours_plan`.
- [ ] Confirm the demo refresh is **not** scheduled against the pilot database
      (`scripts/scheduled_refresh.py`, `.github/workflows/refresh-demo-data.yml`).

## Phase 1 — Operate safely (blocks charging anyone) — PRD §23, §18

Once a real café's closeouts are the only copy of their data, these are not optional.

- [ ] **Tested DB restore drill.** Take a backup of the pilot Neon database and complete a
      restore into a scratch database; record the runbook and the measured restore time.
- [ ] **Failure alerting to a named owner**, each with a one-line runbook:
  - [ ] failed/delayed daily refresh (`scripts/scheduled_refresh.py`),
  - [ ] stale or missing weather (already degrades in-app via the weather seam; add an
        out-of-band alert so nobody relies on noticing the UI),
  - [ ] migration failure (`scripts/migrate.py`).
- [ ] **Hard demo-vs-real guard.** Make it impossible for demo refresh / synthetic truth to run
      against a real tenant — e.g. a per-account `plan`/flag the refresh and `demo_truth` loader
      refuse to cross, tested, not just a convention. (`accounts.plan`, `src/dialin/demo_truth.py`,
      `src/dialin/demo_freshness.py`.)
- [ ] Confirm the app runs only under the low-privilege `dialin_app` role (RLS is enforced by
      the DB; `migrations/002_rls.sql`, `db.assert_not_owner_connection`).
- [ ] **Acceptance:** restore drill recorded; alerts routed; warm p95 Today load < 3s and p95
      closeout→recommendation < 5s for 7 consecutive operating days; missing closeouts/weather
      degrade visibly, never silently.

## Phase 2 — Onboard the location (repeatable setup) — PRD §17.1, §15, §1.1

- [ ] **Economics confirmation as a Day-1 blocking gate.** Capture real `retail_price`,
      `unit_cogs`, salvage, attach rate, and `service_quantile` so `category_economics.values_source`
      leaves `'default'`. Until then the euro headline is untrustworthy (the engine downgrades
      confidence on default economics — `engine._downgrade_confidence` — and the readiness panel
      holds at the setup stage).
- [ ] **Real opening hours and closed days** (`location_hours`, owner-confirmed `source`), so
      comparability and prep targeting are correct.
- [ ] **Categories.** The engine is category-agnostic (`build_recommendations` iterates the
      categories in the data), but the closeout form and the `pos_daily_sales` CHECK are wired to
      `sweet/savory/drinks`. For a café whose menu differs, make category/SKU closeout
      configuration a data change, not a code change (PRD §15, §23).
- [ ] **Cold-start UX for thin history.** A brand-new café trips the
      `engine._forecast_traffic` `base=100.0` fallback at Low confidence — make that explicitly
      labelled "learning your café — advisory only" for the first weeks rather than a silent
      anchor. (The pooled `shared_environment.cold_start_prior` exists but is unfitted by design.)
- [ ] **Repeatable POS onboarding:** reusable column mappings with re-import and reconciliation,
      and audited import failures (`pos_import_runs`, `pos_import_errors`, `src/dialin/pos_import.py`).
- [ ] Define the pilot **baseline** and **live** windows and complete the setup checklist on the
      Setup tab (`repository.pilot`, `pilot_windows` / `pilot_profile`).

## Phase 3 — First operating week (momentum, not a blank scoreboard) — PRD §6.3, §6.5

- [x] **Data-readiness panel.** The owner summary shows *Getting to a verdict* progress during
      the pre-verdict window: economics confirmed → clean closeouts → 28 clean open days →
      recommendation used → value verdict (`metrics.onboarding_readiness`,
      `views/performance._render_readiness`).
- [ ] **Closeout discipline.** Keep `missing_closeout_rate` low; record sellout times and any
      override reasons so attribution and de-censoring stay honest.
- [ ] Watch the operations-health strip (missing closeouts, POS rejects, suspicious jumps) on
      Advanced analysis (`metrics.daily_operations_health`, `metrics.suspicious_operational_jumps`).

## Phase 4 — Prove the decision on real data — PRD §6.4, §12

- [ ] Run a **shadow window** on the real café with recommendation snapshots frozen *before* the
      outcome (`recommendations.input_snapshot` / `config_snapshot` are already captured per row).
- [ ] Compare **Tobit vs comparable-day** de-censoring against **both naive baselines** on the
      **same held-out dates** (`censoring.tobit_decensored_demand`, `engine.decensored_demand_series`,
      `metrics.evaluate_model_vs_baselines`).
- [ ] Nothing drives prep until the per-category gates clear (`metrics.model_gate_report`:
      ≥28 evaluated days, calibrated coverage, low censoring, unbiased, beats both baselines, and a
      robust expected-cost gain). Categories stay `shadow` until then.

## Phase 5 — Prove value and decide pay-again — PRD §6.5

- [ ] Report the **§6.5 value gate** honestly and together: waste proxy, sellout frequency,
      **expected mis-prep cost with its 95% interval** (`metrics.expected_misprep_cost`,
      `savings_robust`), and adherence. The owner summary is the commercial view; Advanced analysis
      is the audit trail behind it.
- [ ] Generate and share the **pilot report** (`pilot_report.build_pilot_report_markdown`) —
      observed / estimated / assumed / not-claimed, with no validated-ROI claim.
- [ ] Answer the one question that decides sellability: **would the owner keep paying?**

> Staffing, ingredients, inventory, and cross-location benchmarking stay out of scope until a
> real café clears both the model gate and the pay-again gate (PRD §23).
