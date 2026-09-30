# Dial In: synthetic data generator and demo app, design

Date: 2026-05-31. Author: Tomasz Solis. Status: implementation design (active scaffold). Companion to `PRD.md` (v1.3).

> Update (2026-06). This is the original design, and some "not in scope (now)" items have shipped since: the real-data right-censored Tobit path (`src/dialin/censoring.py`) and real weather from Open-Meteo now exist next to the censoring-light demo method described below. The demo still defaults to the comparable-day method; Tobit stays advisory until it clears the PRD §6.4 ship gate on real data. See `docs/PRD.md` §23 and `docs/Architecture.md` for the current state.

> Purpose. A clickable, login-gated daily demo of Dial In on synthetic data, built before real Fadri data exists, while learning Docker, Postgres, synthetic data generation, demand forecasting, uncertainty and decisions under asymmetric costs. It shows the daily use case and the engine's behaviour: recommendation, censoring story, newsvendor prep quantity, risk flag. It is not model validation, because planting a demand process and then "recovering" it is circular. Real-data learning comes from a Fadri account once data exists. Nothing here is throwaway: the same provider-neutral Postgres schema and `recommendations` table carry into the Fadri path.

## 1. Scope and non-goals

In scope:

- A reusable synthetic data generator that plants a PRD-faithful demand process with real censoring.
- A target Postgres database (PRD §10 schema plus RLS) seeded with two single-location accounts: a Fadri-style synthetic demo and one dummy café.
- A login-gated Streamlit app (the decant pattern) running the daily loop on the generated observed data with a simplified V1 engine.
- Later, a Fadri real-data account with the same app constraints.

Not in scope (now):

- The logic-proof notebook (later; it reads the planted truth to show censoring recovery).
- POS integration (v1 is manual entry, see §5).
- Production ML models (PRD §11.2) and full real-data Tobit validation. The demo still uses the PRD's decision layer: demand distribution, then newsvendor prep quantity.
- Multi-location, ingredients, staffing, benchmarking.

Honesty boundary: synthetic data shows the flow and engine behaviour, never that the product works. The app and README both say so.

## 2. Architecture: generator, loader, app, offline proof

| Step | Component | Output | Sees planted truth? |
|---|---|---|---|
| 1 | Generator (pure Python, no DB) | `observed/*.parquet` (PRD §10 tables) and `truth/*.parquet` (planted demand) | Produces it |
| 2 | Loader (thin, idempotent, admin role) | Pushes observed only to the target Postgres with RLS | No |
| 3 | App (Streamlit, cloned from decant) | Reads observed rows from the target Postgres, scoped to the account | No |
| 4 | Notebook (later) | Reads local `truth/` and observed database rows for the recovery proof | Yes (offline) |

The parquet step is deliberate: fast generator iteration with no database round trip, an inspectable artifact, the notebook's input and golden test fixtures. Truth stays on disk and is never loaded, so the app can't reach it: by absence, not by convention.

### Decisions made

- Demo goal: a clickable daily app first; the generator stays reusable for the notebook.
- Storage: Postgres first and provider-neutral. Local Docker Postgres 17 is the default development database; Neon free Postgres is the hosted target on Streamlit Community Cloud. Supabase Postgres stays compatible but isn't required.
- Ground truth: fully PRD-faithful, with censoring.
- Tenants: a Fadri-style synthetic demo and one dummy café, one location each, both with history (cold start stays a config toggle, not demoed now). A real Fadri account comes later.
- Daily loop: event-driven. End-of-day entry produces the next-day recommendation at once, readable from then on (evening or morning).
- v1 input: manual entry of 5 numbers (drinks, sweet and savory sold, sweet and savory prepared). Drinks stay so the traffic-to-attach method works.

### Environments

| Environment | App runs on | Database |
|---|---|---|
| Local development | Laptop | Local Docker Postgres 17, via `DATABASE_URL` |
| Hosted demo | Streamlit Community Cloud | Neon free Postgres, via Streamlit secrets and `DATABASE_URL` |
| Fadri real-data path | To be decided | Managed Postgres, only if usage or privacy needs justify it |

The hosted demo can't depend on a local Docker database, so Neon is the hosted demo database. The code stays plain Postgres SQL with no Neon-specific APIs. Neon Auth stays off; `streamlit-authenticator` handles app login.

For the current demo, Streamlit secrets map each login username to one `account_id`. The `account_members` table exists for a later database-owned mapping. Don't run both as independent sources of truth: whichever resolves the tenant must be server-side only, never supplied by the browser.

### Docker learning path

Docker is part of the learning goal, so the local setup stays small and understandable:

1. Install Docker Desktop and check `docker --version` and `docker compose version`.
2. Use `docker-compose.yml` with one service: `postgres:17`.
3. Mount a named volume at `/var/lib/postgresql/data` so local data survives restarts.
4. Use a schema-owner role for migrations and a separate `dialin_app` role for the app. The app role must not own tables.
5. Use `.env.example` with `DATABASE_URL` for the app role and a separate migration/admin URL.
6. Run migrations once the role split is explicit: `migrations/001_init.sql` for schema, constraints, indexes and grants; `migrations/002_rls.sql` for GUC-based RLS on `app.current_account_id`.
7. Document the setup in small steps so Docker is learned, not hidden.

This teaches Docker without blocking the Neon-hosted demo.

## 3. Generator: the planted demand process

Config per café, seeded RNG (reproducible). The causal chain follows PRD §11.1.

The Fadri-style profile is a mixed-focus specialty coffee place, not a coffee-only shop with a few snacks: coffee is central, but sweet and salty vegan baked goods are a real part of the visit, especially at weekends. The scenario to keep in mind is a 09:00 to 13:00 service where food can sell out around 11:30, leaving about 1.5 hours of coffee-only service and missed food sales. This is an assumption about fit, not a claim about all coffee shops.

1. Traffic (drinks): `true_drinks ~ NegBin(mean, k)`, with mean = `base_drinks × weekday_mult × season_curve × weather_effect × event_mult`.
   - Fadri is brunch and weekend heavy; the dummy café is commuter and weekday heavy, so they read as different businesses.
   - Season is an annual sinusoid plus a summer tourism bump. Warm weather lifts footfall up to a point and rain suppresses it. Events multiply (market +30%, marathon +50%).
   - An optional throughput ceiling on peak days plants the §12 "drinks censored on peak days" caveat so it is visible, not just stated.
2. Attach, then pastry demand: per category, `true_demand ~ NegBin(true_drinks × category_attach × adj, k)`. Sweet attach leans weekend and leisure; savory leans weekday morning and commuter.
3. The operator's historical prep-by-gut policy: `prepared = round(trailing_4wk_same_weekday_avg_of_SOLD × habit_factor) + noise`, with `habit_factor` slightly below 1. It deliberately keys off censored `sold`, not demand, which gives chronic under-prep on busy days: the §12 trap. This is the baseline the engine beats.
4. Censoring (the truth/observed split):
   - `observed_sold = min(true_demand, prepared)`
   - `sold_out = observed_sold ≥ prepared − ε` (ε = 1, configurable)
   - `waste = max(prepared − true_demand, 0) × (1 − salvage_share)`
   - `lost_units = max(true_demand − prepared, 0)`, in the truth file only
   - `time_last_sale`: simulated earlier on sellout days from an intraday arrival curve, null otherwise.
5. Weather (forecast and actual): actual from a seasonal climate model for the café's city; `forecast = actual + error that grows with horizon`; `forecast_made_at` stored. This lets the app show §11.4 uncertainty honestly.
6. Events: sparse. A weekly market plus a few festivals and marathons across the window, with impact scores.
7. Believability (see §9): the truth process includes a signal the engine doesn't get (a payday-week bump and a slow regime drift) and an irreducible noise floor, so the V1 engine can't recover demand perfectly and the demo shows honest residual error. The gut policy's `habit_factor` is set at 0.95, not an exaggerated low value.
8. Attach-and-balk sensitivity (a hypothesis, not proof): optionally plant a small drop in drink sales on bad food-sellout days, for customers who would have bought coffee with food but leave when food is gone. Keep it conservative and configurable, and label it as a hypothesis in the demo, or it will overstate recovered revenue.

Horizon: about 18 months, so trailing windows and seasonality are filled, with a flagged demo window (for example the last 30 days) for the replay loop. It ends "yesterday" on the demo clock. A `validate_realism.py` gate (§9) rejects any generated café whose aggregates fall outside plausible bands.

Generator contract:

- Output uses the PRD's account/location/date/category grain. The UI can show sweet and savory side by side, but the rows are long-form, one per category.
- Dates are local business dates. Timestamps are timezone-aware so closeout, forecast horizon and `time_last_sale` can't drift across midnight.
- Closed days exist as `daily_metrics.is_open = false`, have no category demand rows, and are excluded from training.
- The RNG seed, parameters and file hashes go into `truth/run_config.json` so any demo run can be reproduced exactly.

## 4. Parquet contract, Postgres schema, RLS and loader

### Parquet contract

`observed/` (loaded into the target Postgres, exactly PRD §10):

| File | Contents |
|---|---|
| `accounts.parquet` | `account_id, name, plan, contributes_to_shared_layer, cold_start_pool_opt_in, pos_backfill_months, created_at` |
| `locations.parquet` | `account_id, location_id, name, timezone, city, country, open_days, service_capacity_hint, created_at` |
| `daily_metrics.parquet` | One row per account/location/date: open flag, drinks, input source, menu version, recorded timestamp |
| `daily_category_metrics.parquet` | One row per account/location/date/category: sold, prepared, sold-out flag, stockout source, optional last-sale time |
| `weather.parquet` | §10.2 |
| `events.parquet` | §10.3 |
| `category_economics.parquet` | PRD §10.5 economics used to compute `q*` |

`truth/` (local only, never loaded):

| File | Contents |
|---|---|
| `traffic_truth.parquet` | `account_id, location_id, date, true_drinks, throughput_limited` |
| `category_demand_truth.parquet` | `account_id, location_id, date, category, true_demand, lost_units, waste_units, salvage_share` |
| `run_config.json` | Parameters and RNG seed, for full reproducibility |

`recommendations` (§10.4) and `data_corrections` aren't generated. They start empty and the app writes them at runtime.

### Postgres schema

The PRD §10 tables with `account_id` foreign keys, plus `account_members(auth_subject, account_id)`. `recommendations` is long-form by category and stores `input_snapshot_id` and `config_snapshot_id` for replay.

The schema is portable Postgres SQL. Migrations run against local Docker Postgres first, then the same migrations run against Neon for the hosted demo. Supabase Postgres should stay compatible, with no Supabase-specific client APIs, CLI assumptions or auth.

### Isolation (defence in depth, PRD §10.8)

- App layer (primary): one data-access module adds `WHERE account_id = :session_account_id`, with `account_id` from the server-side session only.
- Database layer: the app connects through a dedicated non-owner role. Each transaction runs `SET LOCAL app.current_account_id = …`, and RLS policies read `current_setting('app.current_account_id')`. If the app-layer filter is ever missed, RLS still blocks the other account's rows. The app role must not own tables or bypass RLS.

### Loader

Idempotent (upsert on primary key, or truncate and load, so reseeding is safe). It runs as a platform admin or migration role, not the app role, and pushes `observed/` only, never `truth/`. It fails if any observed file has a column starting with `true_`, a `lost_units` column, or any field that belongs only in `truth/`.

### Connections

- Local development: `DATABASE_URL=postgresql://dialin_app:...@localhost:5432/dialin`
- Hosted demo: `DATABASE_URL=postgresql://dialin_app:...@...neon.tech/dialin?sslmode=require`, stored in Streamlit secrets.
- Migrations and seeding: a separate owner/admin connection, never used by the app.

## 5. App: V1 engine and daily loop

### Engine (`src/dialin/engine.py`, simplified V1)

- Traffic forecast for the target date: trailing 4-week same-weekday mean of drinks × weather adjustment (configured elasticity) × event multiplier.
- Censoring-light correction: on a `sold_out` day, estimated demand = `median(sold on comparable non-sold-out days in the same weekday band × weather bucket) × (day_drinks / bucket_median_drinks)`. That is the comparable-day median, scaled by how busy this day's drinks were. It falls back to `prepared × 1.15` when the bucket has fewer than 5 comparable days. Full Tobit belongs to the notebook.
- Attach rate: de-censored sweet and savory per drink, trailing 4 weeks.
- Distribution: `NegBin(mean = traffic × attach, k)`, with `k` from method of moments on trailing residuals in the condition bucket, falling back to a fitted global `k` with fewer than 10 days.
- Recommendation: `recommended_prep = ceil(NegBin quantile at q*)`, with `q*` from `category_economics` (PRD §10.5, §11.3). The range is p10 to p90. A risk flag shows when prep sits well below the upper band or the censoring rate is high. Confidence (High, Med, Low) comes from censoring rate, history depth and weather forecast error, and widens the range when inputs are shaky (§11.4). The top 3 drivers are the largest weekday, weather and event multipliers.
- Lineage: each recommendation stores target date and category, model version, input snapshot hash, economics/config snapshot hash and generation time. The replay scorecard reads only these rows and observed outcomes.

### Daily loop: event-driven, with replay

The operator's one action is end-of-day entry. On submit, the engine runs and tomorrow's recommendation appears at once and is saved, readable any time after (in the evening to prep overnight, or next morning). Reopening shows the saved recommendation without recomputing.

Replay moves a cursor through the demo window:

1. Submit day N's numbers, then compute and show the day N+1 recommendation, logged to `recommendations` (`date = N+1`, `category in {sweet, savory}`, `generated_at = N evening`).
2. Step forward to reveal day N+1's pre-generated outcome and show Dial In's recommendation vs what the café actually prepped, with cumulative waste and sellout days side by side. This comparison is the demo's payoff.

Limitation, stated in the app: replay compares Dial In with the café's historical actuals. A true counterfactual for a hand-adjusted prep number needs the planted truth the app can't see, which is the later logic notebook. Adjusting numbers in the demo is cosmetic.

### v1 input (manual, before POS)

The operator enters 5 numbers a day: `drinks_sold`, `sweet_sold`, `savory_sold`, `sweet_prepared`, `savory_prepared`. Replay pre-fills them from generated data. That is more than the PRD's one-input target, and accepted as a temporary state until POS exists (see the §7 reconciliation).

### Pages (Streamlit, mobile first per §18)

Login, then the Today/next-day recommendation (landing page), then end-of-day entry (the action), a "Why" expander (drivers), "How Dial In compares" (replay scorecard), and sidebar demo controls (advance or reset the cursor).

### Still needed after the first scaffold

The scaffold proves the loop but doesn't show every model input. That hurts trust: if the app says "make 54" without saying why, the user has to trust a black box. Before the demo counts as complete, add:

- A weather card: target-date forecast, condition, temperature, rain, forecast age, and whether the engine fell back to seasonal normal.
- An event card: confirmed or synthetic local events for the target date, with impact score, source and confidence. Confirmed events must look different from guessed ones.
- A season label: low, mid or high season, or a named tourism or holiday period, tied to the calendar assumptions in the generator and engine.
- Driver explanations with direction and rough lift, not just a multiplier. For example: "Saturday pattern +18%, rain -6%, market +16%."
- Adherence and override capture: once the day is revealed, fill `prepared`, `adhered`, `override_delta` and an optional override reason on the recommendation row.
- Economics assumptions: show whether the service quantile uses confirmed economics or defaults. Don't hide placeholder COGS or margin behind a precise number.
- Scorecard caveats: the scorecard is synthetic and observed-only unless the logic notebook is open. It must show losing days and assumptions, not just the total win.
- Data-quality controls: closed days, late corrections and bad-input repair, before real Fadri data is loaded.

### Intraday and demand-curve demo

The generator already simulates `time_last_sale` on sellout days, but the app doesn't use it. A richer synthetic demo could add opening hours and a daypart curve, labelled as synthetic. In production these claims need POS timestamps.

Planned demo-only additions:

- Synthetic `location_hours` and, optionally, `daypart_truth` artifacts.
- A simple daypart pressure chart: opening hours vs the expected traffic shape.
- A "proxy sellout time" only when `time_last_sale` exists, labelled as observed or synthetic, not inferred fact.
- The recommendation stays daily. The landing page doesn't become an analytics dashboard.

### Error handling

Missing weather falls back to seasonal normal with Low confidence. Manual entries with `sold > prepared` are rejected. Closed days are excluded.

## 6. Honesty boundary

- `truth/` is never loaded, and no truth table exists in the target Postgres for the app role to read.
- Hosted deployments don't include truth files. Local runs keep `truth/` as an offline artifact for validation and the later notebook. Tests check that observed tables have no `true_*`, `lost_units` or planted-demand columns.
- The in-app banner and README say: "Synthetic data. Demonstrates the daily flow and engine behaviour. Not validated; real-data learning comes from the Fadri account." Plus the replay limitation.
- `recommendations` collects replay rows in the same shape the Fadri path uses. Full attribution needs the adherence and override fields filled in later.

## 7. PRD reconciliation (applied with this doc)

This design changes three PRD assumptions, and the PRD was edited to match:

- §4 Principle 2, §6.3 and §7: "exactly one manual input" and "under 30 seconds a day" become post-POS targets. v1 is manual entry of 5 numbers (about 30 to 60 seconds), explicitly temporary.
- §9: `sold` (drinks and pastries) is entered by hand in v1. POS auto-import is a later enhancement, not an MVP assumption.
- §11 cadence: recommendations are generated on end-of-day submit (instant next-day recommendation, readable from the evening), not by a fixed 18:00 job.

## 8. Testing

- Generator invariants: `sold ≤ prepared`; the `sold_out` flag matches the rule; NegBin variance exceeds the mean; no demand on closed days; `weather_forecast ≠ actual` within a bounded horizon error.
- Contract tests: observed parquet files match the PRD grain; truth-only columns never appear in observed files; every observed row has account, location and date keys; category rows exist only on open days.
- Engine: `q*` rises with `Cu/Co`; `recommended_prep` rises with `q*`; de-censoring lifts the trailing mean on sellout-heavy history; the range widens at Low confidence.
- Isolation (assumption register row 7): logged in as account A, queries for B return zero rows, at the app layer and through RLS (set the GUC to A, select B, get nothing).
- Golden fixture: a small committed parquet sample and a snapshot test on one known recommendation.
- Replay honesty: the scorecard can show a day Dial In loses; the app labels the comparison as a synthetic baseline, not real operator impact.

## 9. Believability and honest comparison

The demo should persuade because it's credible, not because it's rigged. Three risks can make a synthetic demo flatter itself, and each has a mitigation.

(a) Realism: the data must look like a real café. Fadri know their own numbers, and fake-looking data loses the room at once. `validate_realism.py` fails generation if any aggregate falls outside the demo's default bands. These bands aren't Fadri facts; they get replaced with Fadri's rough actuals where known:

| Aggregate | Plausible band (illustrative) |
|---|---|
| Base drinks per day | Café-specific once provided |
| Sweet attach (pastries per drink) | 0.30 to 0.45 |
| Savory attach | 0.10 to 0.20 |
| Daily waste (share of prepared) | 5 to 15% |
| Sellout frequency (at least 1 category) | 10 to 30% of open days |
| Weekend to weekday traffic ratio | 1.3 to 1.8 for a brunch-heavy demo profile |

Before the demo uses the Fadri name, it needs rough weekday and weekend drinks, sweet and savory attach ranges, typical prepared volume, sellout frequency, waste and leftover handling, open days and any known market or event rhythm. Without them, the account is labelled fictionalised.

(b) The baseline is deliberately beatable, so say so and don't exaggerate it. The gut policy is biased (`habit_factor < 1`, keyed off censored `sold`) because real gut prepping is. To keep it honest: `habit_factor` is a defensible 0.95, not an inflated low value; the scorecard is always labelled "vs a simulated conservative gut-prepping baseline", never "vs a real operator"; and it reports the days Dial In doesn't win and by how much.

(c) No matched-elasticity flattery. If the generator's weather and event effects are tuned to the engine's adjustments, the demo looks better than reality ever will. So the generator adds (i) a signal the engine ignores (a payday-week bump and a slow regime drift) and (ii) an irreducible noise floor. The engine can't recover demand perfectly, and the demo shows realistic residual error and a believable pinball-loss margin over the naive baseline. Acceptance: the allowed win margin is declared in advance in `validate_realism.py`, and Dial In visibly loses on a minority of days.

In the app, the scorecard shows residual error and losing days, not only the win. Credible beats impressive.

## 10. Build sequence

1. Schema and RLS: provider-neutral Postgres tables, separate owner and app roles, GUC-based RLS policies and cross-account isolation tests.
2. Generator: observed and truth parquet, realism and contract gates, a reproducible `run_config.json`.
3. Loader: seed observed files only, prove it is idempotent, fail on truth leakage.
4. Engine: the simplified V1 recommender with category economics, lineage snapshots and golden recommendation tests.
5. Local database: run migrations against Docker Postgres 17 and check RLS locally.
6. Hosted demo: run the same migrations against Neon free Postgres, store `DATABASE_URL` in Streamlit secrets, deploy the app.
7. App: login, end-of-day entry, recommendation view, replay cursor, scorecard.
8. README: synthetic limits, how to reseed, run tests, use local Docker Postgres, and point the same app at Neon on Streamlit Community Cloud.

## 11. Demo acceptance gates

The demo ships only when all of these hold:

| Gate | Pass condition |
|---|---|
| Data realism | `validate_realism.py` passes on documented bands. Without Fadri bands, the app labels the café as fictionalised. |
| Truth isolation | Observed parquet and target Postgres have no truth-only columns; hosted deployment excludes truth files; no truth table exists. |
| Tenant isolation | Account A can't read account B through app queries or RLS-tested SQL, on local Postgres and on Neon. |
| Decision logic | Recommendations respond correctly to `q*`, weather and event lifts, censoring-heavy history and low-confidence inputs. |
| Honest comparison | The scorecard shows wins and losses and never calls synthetic replay validated ROI. |
| Reproducibility | The same seed and config give the same parquet hashes and golden recommendation. |

## 12. Deferred and open

| Item | State |
|---|---|
| Logic-proof notebook | Reads observed data and local truth to show whether censoring recovery works as claimed. The only place planted truth may be used as proof. |
| Weather visibility | Generated and used, but not shown enough in the UI. Add target weather, forecast age, fallback state and forecast vs actual after reveal. |
| Event visibility and confirmation | Generated and used, but no owner confirmation flow. Hyperlocal events stay semi-manual until source coverage is proven. |
| Season labels | Seasonality exists in generation, but low, mid and high season labels aren't explicit in the app or engine output yet. |
| Opening hours | Only `open_days` today. Add versioned hours before any sellout-time or demand-curve claims. |
| Demand curves | Useful for demos and later staffing, but production curves need timestamped POS data. Synthetic curves must be labelled. |
| Proxy sellout time | `time_last_sale` exists in generated metrics, but the app doesn't compare it with opening hours or remaining service time yet. |
| Accuracy and revenue attribution | The scorecard is a proxy. Add naive baselines, pinball loss, calibration, bias, combined expected cost, assumptions and uncertainty before talking about "revenue generated". |
| Adherence and overrides | The schema has `prepared`, `adhered` and `override_delta`; the app must fill them and capture override reasons. |
| Economics setup | Real `Cu/Co`, salvage, attached-drink margin and attach-and-balk values are placeholders until Fadri input exists. |
| Effect of food stockouts on drinks | `attach_and_balk_rate` is in the PRD, but the demo should only use it as a sensitivity until real Fadri evidence shows whether pastry sellouts reduce drink sales. |
| Data corrections and closed days | Tables and design exist; the app needs a correction workflow and a closed-day action. |
| Cold-start café demo | A config toggle in concept; not built now. |
| POS integration | CSV import first, API integrations later. Timestamp coverage decides whether intraday features can be enabled. |
| Managed auth | `streamlit-authenticator` is fine for the demo. Revisit managed auth only if real usage needs it. |
