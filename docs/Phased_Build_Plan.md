# Dial In phased build plan

Turns the PRD, the synthetic demo design and the current scaffold into standalone build phases. Each phase leaves the app runnable, tested and safe to push to GitHub.

The rule: every phase must make the demo or the product more truthful, without pretending to have data we don't have yet.

## Status (2026-06)

Most of the plan is built; `docs/PRD.md` §23 is the authoritative snapshot. Phases 0 and 3 to 12 are essentially done: stable scaffold and CI, design system, decision-explanation cards, Fadri profile and realism checks, adherence and attribution, economics setup, honest measurement and model gates, opening hours with the daypart curve, CSV POS import, and pilot readiness. From phase 14, real weather (Open-Meteo) and the shared environment-layer estimator are in. Phase 1 (local Docker and RLS) and phases 2 and 13 (hosted Neon deploy) depend on your environment: CI proves RLS, but the hosted deploy is up to the operator. Not started: production intraday claims (they need POS timestamps), staffing, ingredients, inventory, managed auth and POS APIs.

## Phase 0: stabilise the scaffold

Goal: make the local app boring to run.

Build:

- Keep Python pinned to 3.12 in `.python-version` and `pyproject.toml`.
- Keep `uv run ruff check`, `uv run mypy` and `uv run pytest` green.
- Add a smoke test for the Streamlit auth/session helper, without a browser where possible.
- Check generated synthetic data still passes `validate_realism.py`.
- Keep `docs/docker-startup-guide.md` as the step-by-step local runbook.

Done when a fresh clone runs the tests without manual installs, local data generation and validation work, and known Streamlit auth version quirks are documented.

Caution: don't add features until setup is repeatable. A demo that only works on one laptop is state accidentally saved on disk.

## Phase 1: local Postgres and learning Docker

Goal: learn Docker and prove the database path locally before touching hosted data.

Build:

- Start Docker Desktop and run `docker compose up -d postgres`.
- Apply migrations with the owner/admin URL.
- Load observed synthetic data only.
- Run the manual RLS checks from the Docker guide and automate them where possible.
- Add a small database-backed test suite that runs only when `TEST_DATABASE_URL` is set.

Logic: the owner/admin connection migrates and seeds; the app role reads rows only when `app.current_account_id` is set; truth data never enters Postgres.

Done when local Postgres can be rebuilt from scratch, account A can't read account B through app helpers or direct SQL, and tests skip cleanly without Docker.

Caution: don't connect Streamlit Cloud or Neon until RLS is proven locally. Hosted convenience isn't worth leaking tenant data.

## Phase 2: hosted database for the online demo

Goal: run the web app on Neon while keeping the code provider-neutral.

Build:

- Create separate Neon roles: owner/admin for migrations and seeding, `dialin_app` for the Streamlit runtime.
- Apply the same migrations as locally.
- Load observed synthetic data only.
- Check RLS on Neon with the app role.
- Put the runtime `DATABASE_URL` and auth secrets in Streamlit secrets, and keep `MIGRATION_DATABASE_URL` out of the runtime.

Logic: the hosted app uses the low-privilege role only, migration and seed scripts use admin credentials outside the app, and Neon is the demo provider, not the architecture.

Done when Streamlit runs against Neon, the app refuses to start with the owner/admin connection, and RLS checks pass on Neon.

Caution: this is a hosted demo, not production infrastructure. No production claims until backups, monitoring, access audit and deployment controls exist.

## Phase 3: visual design system and UX

Goal: a serious SaaS feel without losing the small-café context.

Direction: take Fadri as domain inspiration (warm, food-aware, specialty coffee, handmade baked goods) and Revolut-style SaaS discipline (clean surfaces, clear hierarchy, restrained cards, fast scanning, confident numbers, little visual noise). Copy neither brand; borrow the operating feel, not the identity.

Build:

- Design tokens: type scale, spacing, colour palette, card and table styles, confidence and risk colours.
- A first screen built around the workflow: target date, sweet recommendation, savory recommendation, range, confidence, why, action state.
- Compact weather, event and season panels below the recommendation.
- A short, mobile-first daily closeout form.
- Analytics below the decision, not above it.

Done when the app looks credible on mobile and desktop, text doesn't overflow, the first screen answers "what should I prep tomorrow?", and it still feels like an operating tool, not a landing page.

Caution: good looks aren't enough. The design must cut decision time. A card that doesn't help the owner decide prep goes below the fold or goes.

## Phase 4: decision explanation

Goal: enough context that the recommendation feels inspectable, not magical.

Build:

| Card | Shows |
|---|---|
| Weather | Target forecast, rain, temperature, condition, when the forecast was made, fallback state when missing |
| Event | Name, type, impact score, source, confidence |
| Season | Low, mid or high season, and any named holiday or tourism period |
| Drivers | Weekday effect, weather effect, event effect, attach-rate and sellout correction |

Logic: the engine already uses weather and events in a basic way, and the UI should show those same inputs, with direction and rough lift instead of hidden maths.

Done when a user can see why a recommendation moved, missing weather lowers confidence and says why, and event impact is labelled as an estimate.

Caution: explanations can turn into storytelling. Keep them tied to actual input values and saved driver multipliers.

## Phase 5: product-fit scenario and synthetic realism

Goal: make the demo match the real target, a mixed-focus specialty coffee place with baked goods.

Build:

- Tune the Fadri-style profile: specialty coffee core; sweet and salty vegan baked goods; weekend spikes; a 09:00 to 13:00 opening window; food sometimes selling out around 11:30; waste aversion from baking in house.
- Keep the dummy café as a contrasting profile.
- Add realism metrics: weekend sellout rate, average sellout time when available, waste share, observed attach rate, drink and food basket sensitivity.

Logic: the product is weak for coffee-only shops with a few cookies, and stronger where fresh food matters and sellouts happen before closing.

Done when the synthetic data looks like the target use case, Fadri is labelled fictionalised unless real operating bands exist, and validation fails if the profile gets too flattering.

Caution: don't rig the baseline. A persuasive demo shows some days where Dial In loses.

## Phase 6: adherence, overrides and attribution

Goal: the attribution backbone, before any pilot, ROI or model-quality claim.

Build:

- After closeout, fill the recommendation's `prepared`, `adhered` and `override_delta`.
- An optional override reason: weather felt wrong, supplier issue, large order, owner judgement, other.
- Adherence in the scorecard, with followed and overridden days split.

Logic: without adherence, you can't tell whether an outcome came from Dial In or from the owner ignoring it. Overrides aren't failures; they show what the model missed. The PRD's measurement claims depend on these fields, so this isn't optional.

Done when recommendation rows reflect actual prep, the scorecard splits adhered and non-adhered days, override reasons are optional and one tap, and no scorecard or pilot report implies attribution before this phase.

Caution: don't over-read adherence. An owner may override for reasons the app couldn't know.

## Phase 7: economics setup and the waste vs run-out control

Goal: a configurable decision layer instead of hidden defaults.

Build:

- An economics view: retail price, unit COGS, salvage share, attached-drink margin, attach-and-balk rate.
- A simple "waste vs run-out" control that maps to the service quantile.
- Each value marked default, owner-confirmed or corrected.
- Lower confidence, or a warning, when economics are defaults.

Logic: the recommendation is a newsvendor decision, and bad economics give precise-looking but wrong advice. The attached-drink effect is a hypothesis until validated.

Done when `category_economics` can be edited safely, past recommendations keep their copied service quantile, and the UI explains the tradeoff without showing formulas by default.

Caution: don't ask owners for more numbers than they can give. Defaults are fine if labelled.

## Phase 8: honest measurement and baselines

Goal: move the scorecard from rough proxy to credible synthetic measurement.

Build:

- Naive baselines: last week's same weekday, and the trailing 4-week same-weekday average.
- Metrics: pinball loss, calibration, mean signed error, censoring rate, waste proxy, sellout frequency, combined expected cost.
- Clear synthetic caveats, and losing days in the scorecard.

Logic: the app optimises expected cost, not raw forecast accuracy. Waste and stockouts move along one curve, so don't claim independent guaranteed cuts in both.

Done when Dial In can be compared with naive baselines on synthetic observed data, the scorecard never says validated ROI, revenue and savings are labelled estimates with assumptions, and calibration and intervals are shown as diagnostics until there are enough held-out open days.

Caution: "revenue generated" is dangerous. Prefer "estimated missed margin recovered" or "combined expected cost reduction", with uncertainty.

## Phase 9: data-quality workflows

Goal: keep bad operational data from poisoning the model.

Build: a closed-day action, a late-correction flow, repair for `sold > prepared`, a data-correction audit view, a menu-version change marker, and basic missing-input handling.

Logic: fresh-prep forecasts are only as good as the closeout data. Missing input must not become zero demand, and regime changes shouldn't be blended blindly into old history.

Done when corrections append to `data_corrections`, closed days produce no category demand rows, and menu changes can be marked and explained.

Caution: a model bug and a data-entry bug can look the same, so the app needs a way to inspect inputs.

## Phase 10: opening hours and a synthetic intraday demo

Goal: keep intraday thinking visible without fake production claims.

Build:

- Versioned `location_hours`.
- Synthetic daypart curve artifacts.
- A demo-only chart: opening hours, expected drink pressure by daypart, and food sellout time when `time_last_sale` exists.
- Sellout time compared with closing time.

Logic: for the target scenario, "sold out at 11:30 while open until 13:00" matters. Production intraday claims need timestamped POS data; until then the demand curve is illustrative.

Done when the demo can show the missed late-service window, the UI says synthetic or illustrative where it should, and the daily recommendation stays the main screen.

Caution: this can easily become fake precision. Keep it labelled as demo until POS timestamps exist.

## Phase 11: CSV POS backfill before API integration

Goal: get closer to real data without over-building integrations.

Build:

- CSV import for historical POS exports.
- Mapping POS rows to drinks, sweet, savory, date and an optional timestamp.
- Validation of imported counts.
- An import summary: rows read, rows rejected, mapped categories, timestamp coverage.

Logic: CSV backfill is cheaper and faster than POS API work, and timestamp coverage decides whether intraday features are allowed.

Done when a pilot café can import historical POS exports, import errors are visible and fixable, and no API credentials are needed yet.

Caution: POS exports are messy. Build mapping and validation before promising automation.

## Phase 12: real pilot readiness

Goal: ready for a friend or pilot café without overstating anything.

Build:

- A pilot setup checklist: open days, operating hours, rough food revenue share, weekend sellout frequency, typical sellout time, waste handling, category economics, POS export availability.
- Shadow mode.
- Baseline and live window tracking.
- An exportable pilot report.
- Manual event confirmation.

Logic: the pilot tests both model quality and business value. If the value is too small, that's a product-fit result, not a reason to sell harder.

Done when a real café can run a short shadow period, the app reports what was observed, estimated and assumed, and no real-data pilot runs without RLS and backups.

Caution: friend pilots are useful but biased. Take the feedback seriously, but don't generalise from it too fast.

## Phase 13: hosted demo polish and release hygiene

Goal: an online demo that's easy to share without embarrassing gaps.

Build: Streamlit Cloud deployment on Neon, online demo instructions in the README, a secrets checklist, basic CI (ruff, mypy, pytest), seed and reset scripts for hosted demo data, and a simple error page for a missing database or secrets.

Logic: a shareable demo needs repeatable deployment, and CI protects the scaffold as features land.

Done when a fresh push passes CI, the hosted demo can be reseeded, and no secrets are committed.

Caution: deployed isn't production-ready.

## Phase 14: later expansion

Goal: keep future ideas visible without distracting from the first use case.

Candidates: real weather API, event-source integrations where coverage is proven, managed auth, POS API integrations, SKU-level prep, ingredients and recipe mapping, staffing suggestions, inventory ordering, multi-location benchmarks within one account, and a shared environment-response model across consenting accounts.

Logic: all plausible, but the first proof is still daily baked-goods prep for mixed-focus specialty coffee places.

Done when earlier phases prove setup, model gates and business value.

Caution: the product can die from breadth. No inventory, staffing or benchmarking until the prep decision is clearly useful.

## Gates for every phase

Every phase ends with:

```bash
uv run ruff check
uv run mypy
uv run pytest
```

When synthetic data changes:

```bash
uv run python scripts/generate_synthetic_data.py --seed 20260531 --output data/generated
uv run python scripts/validate_realism.py data/generated
```

When database behaviour changes:

```bash
uv run python scripts/migrate.py --target local
uv run python scripts/load_observed_data.py --observed-dir data/generated/observed --mode truncate-load
```

Before hosted work: prove RLS locally, use the app role at runtime, use the owner/admin role only for migration and seeding, and never load truth data.

## Suggested next phase

Start with phase 1 if Docker and RLS aren't proven on your machine yet. If they are, do phases 4 and 6 before more polish: explanation plus attribution gives the demo a cleaner truth contract. Then phase 3 visual polish around that workflow.
