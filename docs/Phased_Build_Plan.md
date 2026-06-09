# Dial In Phased Build Plan

This plan turns the PRD, synthetic demo design, and current scaffold into a sequence of
standalone build phases. Each phase should leave the app runnable, testable, and safe to push
to GitHub.

The guiding constraint is simple: every phase must improve the demo or product truth without
pretending we have data we do not have yet.

## Phase 0 — Stabilize The Current Scaffold

Goal: make the current local app boring to run.

Build:
- Keep Python pinned to 3.12 through `.python-version` and `pyproject.toml`.
- Keep `uv run ruff check`, `uv run mypy`, and `uv run pytest` green.
- Add a smoke test for the Streamlit auth/session helper path where possible without launching a browser.
- Confirm generated synthetic data still passes `validate_realism.py`.
- Keep `docs/docker-startup-guide.md` as the hand-holding local runbook.

Done when:
- Fresh clone can run local tests without manual dependency installs.
- Local synthetic data generation and validation work.
- Known Streamlit auth version quirks are documented.

Skeptical note:
- Do not add features until the setup is repeatable. A demo that only works on one laptop is
not a demo; it is state accidentally preserved on disk.

## Phase 1 — Local Postgres And Docker Learning

Goal: learn Docker while proving the database path locally before touching hosted data.

Build:
- Start Docker Desktop.
- Run `docker compose up -d postgres`.
- Apply migrations with the owner/admin URL.
- Load observed synthetic data only.
- Run manual RLS checks from the Docker guide and add automated DB-backed equivalents where possible.
- Add a small DB-backed test suite that runs only when `TEST_DATABASE_URL` is present.

Logic:
- Owner/admin connection can migrate and seed.
- App-role connection can read rows only when `app.current_account_id` is set.
- Truth data must never enter Postgres.

Done when:
- Local Postgres can be reset from scratch.
- Account A cannot read account B through app helpers or direct SQL.
- Tests skip cleanly when Docker is unavailable.

Skeptical note:
- Do not connect Streamlit Cloud or Neon until RLS is proven locally. Hosted convenience is
not worth leaking tenant data.

## Phase 2 — Hosted Database Setup For Online Demo

Goal: make the web app work online with Neon while keeping the code provider-neutral.

Build:
- Create separate Neon roles:
  - owner/admin role for migrations and seed jobs
  - `dialin_app` role for Streamlit runtime
- Apply the same migrations used locally.
- Load observed synthetic data only.
- Verify RLS on Neon with the app role.
- Store runtime `DATABASE_URL` and auth secrets in Streamlit secrets.
- Keep `MIGRATION_DATABASE_URL` out of Streamlit runtime.

Logic:
- The hosted app uses the low-privilege role only.
- Migration/seed scripts use admin credentials outside the app.
- Neon is the demo provider, not the architecture.

Done when:
- Streamlit can run against Neon.
- App refuses to start with the owner/admin connection.
- RLS verification passes on Neon.

Skeptical note:
- This is not production infrastructure. It is a hosted demo. Do not add production claims
until backups, monitoring, access audit, and deployment controls exist.

## Phase 3 — Visual Design System And UX Polish

Goal: make the app feel like a serious SaaS tool without losing the small-cafe context.

Direction:
- Use Fadri as domain inspiration: warm, food-aware, specialty coffee, handmade baked goods.
- Use a Revolut-like SaaS discipline: clean surfaces, clear hierarchy, restrained cards,
fast scanning, confident numbers, low visual noise.
- Do not copy either brand. Borrow the operating feel, not identity.

Build:
- Add design tokens:
  - type scale
  - spacing
  - color palette
  - card/table styles
  - confidence/risk colors
- Redesign the first screen around the actual workflow:
  - target date
  - sweet recommendation
  - savory recommendation
  - range
  - confidence
  - why
  - action state
- Add compact weather/event/season panels below the recommendation.
- Keep the daily closeout form short and mobile-first.
- Keep analytics below the decision, not above it.

Done when:
- The app looks credible on mobile and desktop.
- Text does not overflow.
- The first visible screen answers: "What should I prep tomorrow?"
- The app still feels operational, not like a marketing landing page.

Skeptical note:
- "Beautiful" is not enough. The design must reduce decision time. If a card does not help
the owner decide prep, it belongs below the fold or not at all.

## Phase 4 — Decision Explanation Surface

Goal: show enough context that the recommendation feels inspectable, not magical.

Build:
- Weather card:
  - target forecast
  - rain/temp/condition
  - forecast made at
  - fallback state when missing
- Event card:
  - event name
  - event type
  - impact score
  - source
  - confidence
- Season card:
  - low/mid/high season
  - named holiday/tourism period when relevant
- Driver explanation:
  - weekday effect
  - weather effect
  - event effect
  - attach-rate/sellout correction

Logic:
- The engine already uses weather/events in a basic way.
- The UI should expose those same inputs.
- The explanation should show direction and rough lift, not hidden math.

Done when:
- A user can see why a recommendation moved up or down.
- Missing weather lowers confidence and says why.
- Event impact is labelled as estimated, not fact.

Skeptical note:
- Explanations can become storytelling. Keep them tied to actual input values and stored
driver multipliers.

## Phase 5 — Product-Fit Scenario And Synthetic Realism

Goal: make the synthetic demo match the real wedge: mixed-focus specialty coffee plus baked goods.

Build:
- Tune the Fadri-style profile around:
  - specialty coffee core
  - sweet and salty vegan baked goods
  - weekend demand spikes
  - 09:00-13:00 opening window
  - food sometimes selling out around 11:30
  - waste aversion from in-house baking
- Keep the dummy cafe as a contrasting profile.
- Add realism metrics:
  - weekend sellout rate
  - average sellout time when available
  - waste share
  - observed attach rate
  - drink/food basket sensitivity

Logic:
- This product is weak for coffee-only shops with incidental cookies.
- It is stronger where fresh food is meaningful and sellouts happen before close.

Done when:
- The synthetic data looks like the target use case.
- The app labels Fadri as fictionalized unless real operating bands are supplied.
- Validation fails if the synthetic profile becomes too flattering.

Skeptical note:
- Do not rig the baseline. A persuasive demo should show some days where Dial In loses.

## Phase 6 — Adherence, Overrides, And Attribution Basics

Goal: complete the attribution backbone before any pilot, ROI, or model-quality claim.

Build:
- After closeout, populate recommendation fields:
  - `prepared`
  - `adhered`
  - `override_delta`
- Add optional override reason:
  - weather felt wrong
  - supplier issue
  - large order
  - owner judgement
  - other
- Show adherence in the scorecard.
- Separate days followed vs days overridden.

Logic:
- Without adherence, we cannot tell whether outcomes came from Dial In or from the owner
ignoring the recommendation.
- Overrides are not failure. They are evidence about what the model missed.
- This is not optional polish. The PRD's measurement claims depend on these fields existing.

Done when:
- Recommendation rows reflect actual closeout prep.
- Scorecard can split adhered and non-adhered days.
- Override reasons are optional and one tap.
- No scorecard or pilot report implies attribution before this phase is done.

Skeptical note:
- Do not over-interpret adherence. An owner may override for reasons the app could not know.

## Phase 7 — Economics Setup And Waste-Vs-Runout Control

Goal: make the decision layer configurable instead of relying on hidden defaults.

Build:
- Add an economics setup view:
  - retail price
  - unit COGS
  - salvage share
  - attached-drink margin
  - attach-and-balk rate
- Add a simple "waste vs run-out" control that maps to service quantile.
- Mark values as:
  - default
  - owner-confirmed
  - corrected
- Lower confidence or show a warning when economics are defaults.

Logic:
- The recommendation is a newsvendor decision.
- Bad economics create precise-looking but wrong prep advice.
- The attached-drink effect is a hypothesis until validated.

Done when:
- `category_economics` can be edited safely.
- Historical recommendations keep their copied service quantile.
- The UI explains the tradeoff without showing formulas by default.

Skeptical note:
- Do not ask owners for more numbers than they can realistically provide. Defaults are fine,
but they must be labelled.

## Phase 8 — Honest Measurement And Baselines

Goal: improve the scorecard from rough proxy to credible synthetic measurement.

Build:
- Add naive baselines:
  - last-week same weekday
  - trailing 4-week same weekday average
- Add metrics:
  - pinball loss
  - calibration
  - mean signed error
  - censoring rate
  - waste proxy
  - sellout frequency
  - combined expected cost
- Show synthetic caveats clearly.
- Add losing days to the scorecard.

Logic:
- The app optimizes expected cost, not raw forecast accuracy.
- Waste and stockout move along one curve; do not claim independent guaranteed reductions.

Done when:
- Dial In can be compared to naive baselines on synthetic observed data.
- The scorecard never says validated ROI.
- Revenue/savings are labelled as estimates with assumptions.
- Calibration and confidence intervals are shown as diagnostics until there are enough held-out open days to support them.

Skeptical note:
- "Revenue generated" is dangerous phrasing. Prefer "estimated missed margin recovered" or
"combined expected cost reduction," with uncertainty.

## Phase 9 — Data Quality Workflows

Goal: keep bad operational data from poisoning the model.

Build:
- Closed day action.
- Late correction flow.
- Bad input repair for `sold > prepared`.
- Data correction audit display.
- Menu-version change marker.
- Basic missing-input handling.

Logic:
- Fresh-prep forecasting is only as good as the closeout data.
- Missing input should not become zero demand.
- Regime changes should not be blended into old history blindly.

Done when:
- Corrections append to `data_corrections`.
- Closed days do not produce category demand rows.
- Menu changes can be marked and explained.

Skeptical note:
- A model bug and a data-entry bug can look identical. The app needs a way to inspect inputs.

## Phase 10 — Opening Hours And Synthetic Intraday Demo

Goal: keep intraday thinking visible while avoiding fake production claims.

Build:
- Add versioned `location_hours`.
- Add synthetic daypart curve artifacts.
- Show a demo-only chart:
  - opening hours
  - expected drink pressure by daypart
  - food sellout time when `time_last_sale` exists
- Compare sellout time to close time.

Logic:
- For the target scenario, "sold out at 11:30 while open until 13:00" is important.
- Production intraday claims require timestamped POS data.
- Until then, the demand curve is illustrative.

Done when:
- Synthetic demo can show the missed late-service window.
- UI clearly says synthetic/illustrative where appropriate.
- Daily recommendation remains the main screen.

Skeptical note:
- This feature can easily become fake precision. Keep it demo-labelled until POS timestamps
exist.

## Phase 11 — CSV POS Backfill Before API Integration

Goal: get closer to real data without overbuilding integrations.

Build:
- CSV import for historical POS exports.
- Map POS rows to:
  - drinks
  - sweet
  - savory
  - date
  - optional timestamp
- Validate imported counts.
- Store import summary:
  - rows read
  - rows rejected
  - mapped categories
  - timestamp coverage

Logic:
- CSV backfill is cheaper and faster than POS API work.
- Timestamp coverage decides whether intraday features are allowed.

Done when:
- A pilot cafe can import historical POS exports.
- Import errors are visible and fixable.
- No API credentials are needed yet.

Skeptical note:
- POS exports are messy. Build mapping and validation before promising automation.

## Phase 12 — Real Pilot Readiness

Goal: prepare the product for friend/pilot usage without overstating it.

Build:
- Pilot setup checklist:
  - open days
  - operating hours
  - rough food revenue share
  - weekend sellout frequency
  - typical sellout time
  - waste handling
  - category economics
  - POS export availability
- Shadow mode.
- Baseline/live window tracking.
- Exportable pilot report.
- Manual event confirmation.

Logic:
- The pilot should test both model quality and business value.
- If value is too small, that is a product-fit result, not a failure to sell harder.

Done when:
- A real cafe can run a short shadow period.
- The app can report what was observed, estimated, and assumed.
- No real-data pilot runs without RLS and backups.

Skeptical note:
- Friend pilots are useful but biased. Treat feedback seriously, but do not generalize too
quickly.

## Phase 13 — Hosted Demo Polish And Release Hygiene

Goal: make the online demo easy to share without embarrassing operational gaps.

Build:
- Streamlit Cloud deployment against Neon.
- README online demo instructions.
- Secrets checklist.
- Basic CI:
  - ruff
  - mypy
  - pytest
- Seed/reset scripts for hosted demo data.
- Simple error page for missing DB/secrets.

Logic:
- A shareable demo needs repeatable deployment.
- CI protects against breaking the scaffold as features are added.

Done when:
- Fresh push passes CI.
- Hosted demo can be reseeded.
- No secrets are committed.

Skeptical note:
- Do not confuse "deployed" with "production-ready."

## Phase 14 — Later Product Expansion

Goal: keep future ideas visible without letting them distract the first wedge.

Candidates:
- Real weather API integration.
- Event-source integrations where coverage is proven.
- Managed auth.
- API POS integrations.
- SKU-level prep.
- Ingredients and recipe mapping.
- Staffing suggestions.
- Inventory ordering.
- Multi-location benchmarking within one account.
- Shared environment-response model across consenting accounts.

Logic:
- These are plausible, but the first proof is still daily baked-goods prep for mixed-focus
specialty coffee places.

Done when:
- Earlier phases prove setup, model gates, and business value.

Skeptical note:
- The product can die from breadth. Do not build inventory, staffing, or benchmarking until
the prep decision is clearly useful.

## Always-On Gates

Every phase should end with:

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

When database behavior changes:

```bash
uv run python scripts/migrate.py --target local
uv run python scripts/load_observed_data.py --observed-dir data/generated/observed --mode truncate-load
```

Before hosted work:
- prove RLS locally
- use app role at runtime
- use owner/admin role only for migration/seed
- do not load truth data

## Suggested Immediate Next Phase

Start with Phase 1 if Docker/RLS has not been fully proven on your machine. If that is already
done, move to Phase 4 and Phase 6 before broader polish: explanation plus attribution gives the
demo a cleaner truth contract. Then do Phase 3 visual polish around that workflow.
