# Dial In — Synthetic Data Generator & Demo App — Design

**Date:** 2026-05-31
**Author:** Tomasz Solis
**Status:** Implementation design (pre-build)
**Companion to:** `PRD.md` (v3.2)

> **Purpose.** Stand up a clickable, login-gated daily demo of Dial In on **synthetic data**, before real pilot data (Fadri café, fadri.cafe) is available. It demonstrates the **daily use case and the engine's behaviour** — recommendation, censoring story, newsvendor prep quantity, risk flag. It is **not** model validation: planting a demand process and then "recovering" it would be circular. Validation comes from the Fadri pilot. The generator and schema are built so nothing here is throwaway — the same Supabase shape and `recommendations` table carry into the pilot.

---

## 1. Scope & non-goals

**In scope**
- A reusable **synthetic data generator** that plants a PRD-faithful demand process with real censoring.
- A **Supabase** warehouse (PRD §10 schema + RLS) seeded with two accounts: **Fadri** and **one dummy café**, single-location each.
- A **login-gated Streamlit app** (decant pattern) running the daily loop on the generated *observed* data with a simplified V1 engine.

**Not in scope (now)**
- The logic-proof notebook (later; reads the planted truth to show censoring recovery).
- POS integration (v1 is manual entry — see §5).
- Production ML models (PRD §11.2) and full pilot-grade Tobit validation. The demo still uses the PRD's decision layer: demand distribution → newsvendor prep quantity.
- Multi-location, ingredient/staffing, benchmarking.

**Honesty boundary.** Synthetic data demonstrates *flow and engine behaviour*, never *that the product works*. Stated in-app and in the README.

---

## 2. Architecture — generator, loader, app, offline proof

| Step | Component | Output | Sees planted truth? |
|---|---|---|---|
| 1 | **Generator** (pure Python, no DB) | `observed/*.parquet` (PRD §10 tables) + `truth/*.parquet` (planted demand) | produces it |
| 2 | **Loader** (thin, idempotent, service role) | pushes **observed only** → Supabase + RLS | no |
| 3 | **App** (Streamlit, decant-clone) | reads Supabase observed, account-scoped | no |
| 4 | **Notebook** (later) | reads local `truth/` + Supabase observed → recovery proof | yes (offline) |

The parquet intermediate is deliberate: fast generator iteration with no DB round-trip, an inspectable artifact, the notebook's fixture, and golden test fixtures. **Truth stays on disk and is never loaded** — so the app has no path to it by absence, not convention.

### Locked decisions
- Demo goal: **clickable daily app first** (generator reusable for the notebook later).
- Storage: **Supabase from day one** (Postgres + RLS + `streamlit-authenticator`), pilot-ready.
- Ground truth: **full PRD-faithful + censoring**.
- Tenants: **Fadri + 1 dummy café**, single-location each, both populated with history (cold-start stays a config toggle, not demoed now).
- Daily loop: **event-driven** — EOD data entry produces the next-day recommendation instantly; readable from then on (evening or morning).
- v1 input: **manual entry of all 5 numbers** (drinks + sweet/savory sold + sweet/savory prepared); drinks kept to preserve the traffic→attach method.

---

## 3. Generator — the planted demand process

Per-café config, seeded RNG (reproducible). Causal chain mirrors PRD §11.1.

1. **Traffic (drinks):** `true_drinks ~ NegBin(mean, k)`, mean = `base_drinks × weekday_mult × season_curve × weather_effect × event_mult`.
   - Fadri ≈ brunch/weekend-heavy; dummy café ≈ commuter/weekday-heavy (the two read as visibly different businesses).
   - season = annual sinusoid + summer tourism bump; weather = warm lifts footfall to a point, rain suppresses; events multiply (market +30%, marathon +50%).
   - Optional **throughput ceiling** on peak days → plants the §12 "drinks censored on peak days" caveat so it is visible, not just asserted.
2. **Attach → pastry demand:** for each category, `true_demand ~ NegBin(true_drinks × category_attach × adj, k)`. Sweet attach skews weekend/leisure; savory skews weekday-morning/commuter.
3. **Operator "prep-by-gut" policy (historical):** `prepared = round(trailing_4wk_same_weekday_avg_of_SOLD × habit_factor) + noise`, `habit_factor` slightly < 1. **Deliberately keys off censored `sold`, not demand** → chronic under-prep on high days, exactly the §12 trap. This is the baseline the engine beats.
4. **Censoring (truth/observed split):**
   - `observed_sold = min(true_demand, prepared)`
   - `sold_out = observed_sold ≥ prepared − ε` (ε = 1, configurable)
   - `waste = max(prepared − true_demand, 0) × (1 − salvage_share)`
   - `lost_units = max(true_demand − prepared, 0)` → **truth file only**
   - `time_last_sale`: simulated earlier on sellout days from an intraday arrival curve; null otherwise.
5. **Weather (forecast + actual):** actual from a seasonal climate model for the café city; `forecast = actual + horizon-growing error`; store `forecast_made_at`. Lets the app show §11.4 uncertainty honestly.
6. **Events calendar:** sparse — recurring weekly market + a handful of festivals/marathons across the window, with impact scores.
7. **Believability injections (anti-flattery — see §9):** the truth process includes a **signal the engine is not given** (a payday-week bump + a slow regime drift) and an **irreducible noise floor**, so the V1 engine cannot perfectly recover demand and the demo shows honest residual error. The gut-policy `habit_factor` is anchored to **0.95**, not an exaggerated low value.

**Horizon:** ~18 months, so trailing windows and seasonality are populated; includes a flagged **demo window** (e.g. last 30 days) for the replay loop. Ends "yesterday" on the demo clock. A `validate_realism.py` gate (§9) rejects any generated café whose aggregates fall outside plausible café bands.

**Generator contract.**
- Output uses the PRD's account/location/date/category grain. The UI may show sweet and savory side by side, but the generated rows are long-form category rows.
- Dates are local business dates. Timestamps carry timezone-aware values so closeout, forecast horizon, and `time_last_sale` cannot drift across midnight.
- Closed days exist as `daily_metrics.is_open = false`; they have no category demand rows and are excluded from training.
- The RNG seed, parameter set, and generated file hashes are written to `truth/run_config.json` so any demo run can be reproduced exactly.

---

## 4. Parquet contract + Supabase schema, RLS & loader

### Parquet contract
`observed/` (loaded to Supabase — exactly PRD §10):
- `accounts.parquet` — `account_id, name, plan, contributes_to_shared_layer, cold_start_pool_opt_in, pos_backfill_months, created_at`
- `locations.parquet` — `account_id, location_id, name, timezone, city, country, open_days, service_capacity_hint, created_at`
- `daily_metrics.parquet` — one row per account/location/date: open flag, drinks, input source, menu version, recorded timestamp
- `daily_category_metrics.parquet` — one row per account/location/date/category: sold, prepared, sold-out flag, stockout source, optional last-sale time
- `weather.parquet` — §10.2
- `events.parquet` — §10.3
- `category_economics.parquet` — PRD §10.5 economics inputs used to compute `q*`

`truth/` (local only, never loaded):
- `traffic_truth.parquet` — `account_id, location_id, date, true_drinks, throughput_limited`
- `category_demand_truth.parquet` — `account_id, location_id, date, category, true_demand, lost_units, waste_units, salvage_share`
- `run_config.json` — params + RNG seed (full reproducibility)

`recommendations` (§10.4) and `data_corrections` are **not generated** — they start empty, and the app writes them at runtime.

### Supabase schema
The PRD §10 tables, `account_id` FKs, plus `account_members(auth_subject, account_id)`. `recommendations` is long-form by category and stores `input_snapshot_id` and `config_snapshot_id` for replay.

### Isolation (defense-in-depth, PRD §10.8)
- **App layer (primary):** single data-access module injects `WHERE account_id = :session_account_id`; `account_id` from server-side session only.
- **DB layer (real RLS without Supabase Auth):** app connects via a dedicated **non-owner `app_role`**; each transaction runs `SET LOCAL app.current_account_id = …`; RLS policies read `current_setting('app.current_account_id')`. If the app-layer filter is ever forgotten, RLS still blocks the cross-account row.

### Loader
Idempotent (upsert on PK / truncate+load so reseed is safe), runs as **owner/service role** (bypasses RLS for seeding), pushes `observed/` only, never `truth/`. The loader fails if any observed file contains a column prefixed with `true_`, `lost_units`, or any field listed only under `truth/`.

---

## 5. App — V1 engine + daily loop

### Engine (`engine/recommend.py`, simplified V1)
- **Traffic forecast** for target date = trailing-4wk same-weekday mean of drinks × weather adjustment (configured elasticity) × event multiplier.
- **Censoring-light correction (pinned):** on a `sold_out` day, impute demand = `median(sold of comparable non-sold-out days in the same weekday-band × weather-bucket) × (day_drinks / bucket_median_drinks)` — the comparable-day median scaled by how busy *this* day's drinks were. Falls back to `prepared × 1.15` when the bucket has < 5 comparable days. Full Tobit is the notebook's job.
- **Attach rate:** de-censored sweet/savory per drink, trailing 4wk.
- **Distribution (pinned):** `NegBin(mean = traffic × attach, k)`; `k` by method-of-moments on trailing residuals within the condition bucket, falling back to a fitted global `k` when the bucket has < 10 days.
- **Recommendation:** `recommended_prep = ceil(NegBin quantile at q*)`, `q*` from `category_economics` (PRD §10.5, §11.3). Range = p10/p90. **Risk flag** when prep sits well below the upper band or censoring rate is high. **Confidence** (High/Med/Low) from censoring rate + history depth + weather-forecast error, widening the range when inputs are shaky (§11.4). **Top-3 drivers** = largest weekday/weather/event multipliers.
- **Lineage:** each recommendation stores the target date/category, model version, input snapshot hash, economics/config snapshot hash, and generated timestamp. The replay scorecard reads only these recommendation rows plus observed outcomes.

### Daily loop — event-driven, replay mode
The operator's single action is **end-of-day data entry**. On submit, the engine runs and **tomorrow's recommendation renders immediately** and persists — readable any time after (evening to prep overnight, or next morning). Reopening shows the stored rec; no recompute.

Demo replay walks a cursor through the generated demo window:
1. Submit day N's numbers → compute & show day **N+1** recommendation, logged to `recommendations` (`date = N+1`, `category in {sweet, savory}`, `generated_at = N evening`).
2. Step forward → reveal day N+1's pre-generated outcome and show **Dial In's rec vs what the café actually prepped** — cumulative waste & sellout days side by side. This comparison is the demo's payoff.

**Stated limitation (in-app):** replay compares Dial In to the café's *historical actual*. A true counterfactual on a hand-nudged prep number needs the planted truth the app can't see → that is the logic notebook, later. Nudging in the demo is cosmetic.

### v1 input (manual, pre-POS)
Operator types 5 numbers/day: `drinks_sold`, `sweet_sold`, `savory_sold`, `sweet_prepared`, `savory_prepared`. Pre-filled in replay from generated data. This is heavier than the PRD's one-input target — accepted as a temporary pre-POS state (see §7 reconciliation).

### Pages (Streamlit, mobile-first per §18)
Login → **Today/next-day recommendation** (landing, the readable rec) → **EOD entry** (the action) → **"Why"** expander (drivers) → **"How Dial In compares"** (replay scorecard) → sidebar demo controls (advance/reset cursor).

### Error handling
Missing weather → seasonal normal + Low confidence. `sold > prepared` rejected on manual entry. Closed days excluded.

---

## 6. Honesty boundary
- `truth/` never loaded; no truth table exists in Supabase for `app_role` to read.
- The app role has no filesystem access to generated truth files. Tests verify that observed tables contain no `true_*`, `lost_units`, or planted-demand columns.
- In-app banner + README: "Synthetic data — demonstrates the daily flow and engine behaviour. Not validated; validation comes from the Fadri pilot." Plus the replay limitation.
- `recommendations` accumulates genuine attribution rows during replay — same shape the pilot uses.

---

## 7. PRD reconciliation (applied alongside this doc)
This design changes three PRD assumptions; PRD v3.2 is edited to match so the two documents do not contradict:
- **§4 Principle 2 / §6.3 / §7:** "exactly one manual input" and "<30s/day" are reframed as **post-POS targets**; **v1 is manual entry of 5 numbers** (~30–60s), explicitly temporary.
- **§9:** `sold` (drinks/pastries) is **manually entered in v1**; POS auto-import moves to a later enhancement, not an MVP assumption.
- **§11 cadence:** recommendation generation is **event-driven on EOD submit** (instant next-day rec, readable evening-onward), not a fixed ~18:00 job.

---

## 8. Testing
- **Generator invariants:** `sold ≤ prepared`; `sold_out` flag matches the rule; NegBin variance > mean; no demand on closed days; `weather_forecast ≠ actual` within bounded horizon error.
- **Contract tests:** observed parquet files match the PRD grain; truth-only columns never appear in observed files; every observed row has account/location/date keys; category rows exist only for open days.
- **Engine:** `q*` monotonic in `Cu/Co`; `recommended_prep` rises with `q*`; de-censoring lifts trailing mean on sellout-heavy history; range widens when confidence Low.
- **Isolation (PRD §20 row 7):** logged in as account A → queries for B return zero rows, at app layer **and** via RLS (set GUC to A, select B → empty).
- **Golden fixture:** small committed parquet sample + snapshot test on one known recommendation.
- **Replay honesty:** scorecard can show a losing Dial In day; app copy labels the comparison as synthetic baseline, not real operator impact.

---

## 9. Believability & honest comparison *(so the demo persuades because it's credible, not because it's rigged)*

Three risks turn a synthetic demo into a self-flattering one. Each is mitigated explicitly.

**(a) Realism anchoring — the data must look like a real café.** Fadri know their own numbers; fake-looking data loses the room on sight. A `validate_realism.py` gate fails generation if any aggregate falls outside demo default bands. These are not Fadri facts; they are replaced with Fadri's rough actuals where known:

| Aggregate | Plausible band (illustrative) |
|---|---|
| Base drinks/day | café-specific once provided |
| Sweet attach (pastries/drink) | 0.30–0.45 |
| Savory attach | 0.10–0.20 |
| Daily waste (of prepared) | 5–15% |
| Sellout frequency (≥1 category) | 10–30% of open days |
| Weekend:weekday traffic ratio | 1.3–1.8 for a brunch-heavy demo profile |

Minimum Fadri inputs before using the Fadri name in-demo: rough weekday/weekend drinks, sweet and savory attach range, typical prepared volume, sellout frequency, waste/leftover handling, open days, and any known market/event cadence. If those are not available, the account is labelled fictionalised.

**(b) The baseline is deliberately beatable — so we say so and don't exaggerate it.** The gut-policy is biased (`habit_factor < 1`, keyed off censored `sold`) *because real gut-prepping is*. To keep it honest: `habit_factor` is anchored to a defensible **0.95** (not an inflated low value); the scorecard is always labelled **"vs a simulated conservative gut-prepping baseline," never "vs a real operator";** and it reports the **days Dial In does *not* win and by how much**, not just the headline.

**(c) No matched-elasticity flattery.** If the generator's weather/event effects and the engine's adjustments are tuned to each other, the demo looks better than reality ever will. So the generator injects (i) **a signal the engine ignores** (e.g. a payday-week bump and a slow regime drift) and (ii) an **irreducible noise floor**. The engine therefore cannot perfectly recover demand; the demo shows realistic residual error and a **believable** pinball-loss margin over the naive baseline — not an implausible one. Acceptance: the allowed win margin is pre-declared in `validate_realism.py`, and Dial In visibly loses on a minority of days.

**In-app:** the scorecard surfaces residual error and loss-days, not just the win. Credible beats impressive.

---

## 10. Build sequence
1. **Schema and RLS:** create Supabase tables, `app_role`, GUC-based RLS policies, and cross-account isolation tests.
2. **Generator:** produce observed/truth parquet, run realism and contract gates, write reproducible `run_config.json`.
3. **Loader:** seed observed files only, prove idempotency, and fail on truth leakage.
4. **Engine:** implement the simplified V1 recommender with category economics, lineage snapshots, and golden recommendation tests.
5. **App:** login, EOD entry, recommendation view, replay cursor, and scorecard.
6. **README:** state synthetic limits, how to reseed, how to run tests, and what still needs Fadri pilot data.

---

## 11. Demo acceptance gates
The demo is shippable only when all hold:

| Gate | Pass condition |
|---|---|
| Data realism | `validate_realism.py` passes using documented bands; if Fadri bands are unavailable, the app labels the café as fictionalised |
| Truth isolation | observed parquet and Supabase contain no truth-only columns; app role cannot read local truth files or any truth table |
| Tenant isolation | account A cannot read account B through app queries or direct RLS-tested SQL |
| Decision logic | recommendations respond correctly to `q*`, weather/event lifts, censoring-heavy history, and low-confidence inputs |
| Comparison honesty | scorecard shows wins and losses, and never describes synthetic replay as validated ROI |
| Reproducibility | same seed and config produce the same parquet hashes and golden recommendation |

---

## 12. Deferred / open
- Logic-proof notebook (censoring recovery against truth).
- Cold-start café demo (config toggle exists; not built now).
- POS integration; Supabase Auth (vs `streamlit-authenticator` + GUC-RLS); intraday/Phase-2.
- Real `Cu/Co`, salvage, attach-and-balk values — placeholders until Fadri data.
