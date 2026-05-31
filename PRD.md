# Dial In — Product Requirements Document (PRD)

**Version:** 1.1
**Author:** Tomasz Solis
**Status:** Draft
**Created:** 2026-05-31
**Last updated:** 2026-05-31
**Companion:** `2026-05-31-synthetic-data-and-demo-design.md` (demo/generator design; v1 input & cadence reconciled here)
**Product Type:** SaaS / decision tool
**Target Market:** Independent cafés, specialty coffee shops, bakeries, brunch restaurants

> **TL;DR** — Dial In answers one question for an independent café owner each morning: *how much fresh food do I prep today?* It is a **decision tool, not a forecasting dashboard**. The hard part is not predicting sales — it is that sales are **censored** (you never see demand above what you baked) and the cost of a stockout is not equal to the cost of waste. Dial In treats prep as a **newsvendor decision**: forecast the demand *distribution*, then pick the prep quantity that minimises expected cost given the café's own margin and waste economics. It works from **day one by importing the café's own POS history** (most cafés already hold 1–2 years), leans on a **shared weather/event benchmark** for conditions any single café sees too rarely to learn, and **proves its own impact** through logged recommendation-vs-outcome data and a staged rollout.

---

## 1. Executive Summary

Independent cafés decide food prep by gut. The decision is high-frequency (daily), irreversible (fresh food can't be un-baked), and asymmetric (running out costs more than throwing out). Owners get it wrong in both directions and have no time to analyse why.

Dial In recommends a daily prep quantity per product category, with a demand range and the reasons behind it. The operator closes out the day's numbers and the next day's recommendation appears instantly, readable that evening or the next morning. It uses sales history, weather and event forecasts, and seasonality. In **v1 the day's numbers are entered manually** (~30–60s); once POS integration lands, `sold` is auto-imported and daily effort drops toward the <30s / one-input target.

Three things separate Dial In from "a forecast in an app":

1. **It optimises a decision, not an accuracy score.** The output is the prep quantity that minimises expected money lost — explicitly trading waste cost against stockout cost — not the most likely sales number.
2. **It corrects for censored demand.** It distinguishes "sold 40 because demand was 40" from "sold 40 because we only made 40 and ran out", and learns from both correctly.
3. **It is measurable.** Every recommendation, the operator's actual decision, and the realised outcome are logged, so impact can be attributed rather than asserted.

---

## 2. Problem Statement

Independent cafés rely on intuition to decide daily prep. Intuition breaks down under variance: weather swings, tourism, local events, seasonality, and weekday/weekend differences each move demand by amounts an owner can't hold in their head simultaneously.

The result is one of two errors, every single day:

### Under-preparation (stockout)
Too little prepared; items sell out before demand ends.
- **Cost:** lost margin on every unmet sale, lower average order value (no pastry attached to the coffee), disappointed regulars, staff stress.
- **It is also invisible in the data.** When you sell out, your sales number stops at what you baked — you never observe how much more you *could* have sold. This is the core measurement problem (see §12).

### Over-preparation (waste)
Too much prepared; surplus is binned, discounted, or eaten by staff.
- **Cost:** wasted COGS, thinner margins, wasted labour, and for many owners a genuine ethical sting.

### Why these are not symmetric
A stockout typically costs **2–4× more per unit** than waste: a missed croissant loses the full retail margin (~€2.60 on a €3.50 item), while an unsold one loses only its COGS (~€0.90). [Likely — exact ratio is café-specific and configured per customer.] **Any tool that tries to minimise both errors equally is solving the wrong problem.** Dial In encodes this asymmetry explicitly (see §6, §11).

---

## 3. Product Vision

Dial In is the operational copilot for fresh-food prep in independent cafés. When the operator closes out the day, the next day's recommendation appears — readable that evening (to prep overnight) or the next morning — and reads like a weather forecast, just as quick to consume:

**Example recommendation:**
- **Expected traffic:** 190–220 drinks
- **Recommended prep:**
  - Sweet pastries: **54** (demand range 46–61, prep set at the ~78th percentile per §11.3)
  - Savory pastries: **31** (demand range 25–36)
- **Risk flag:** High demand likely — sunny Saturday + local market
- **Confidence:** High (similar to 18 comparable past days)

The operator absorbs everything in under 30 seconds and gets on with their day.

---

## 4. Product Principles

1. **Low friction beats marginal accuracy.** A good-enough model used every day beats a great model that needs babysitting. Owner effort budget: **< 30 seconds/day, < 15 minutes onboarding** — a **post-POS target**. In **v1 (pre-POS), input is manual** (drinks + sweet/savory sold + sweet/savory prepared, ~30–60s); the budget tightens once POS auto-supplies `sold` (see §9).
2. **Every manual input must justify itself — and be protected.** `prepared` is the input that can never be automated, because it is the only way to detect a stockout; in v1 the operator also enters `sold` until POS integration lands. Because the model leans on these, we validate them, not just request them (see §10.6).
3. **Recommend, don't report.** The default screen is a decision, not a dashboard. Analytics exist, but never on the landing screen.
4. **Optimise expected money, not forecast error.** Forecast accuracy is a means; the end is the prep quantity that loses the least money given this café's economics.
5. **Be honest about uncertainty.** When the model is guessing (new café, volatile weather, unusual event), it says so and widens the range rather than faking a confident number.

---

## 5. Target Customer

### Primary
**Independent specialty coffee shops & artisan bakeries**
- 1 location, 2–10 staff, owner-operated, significant fresh-food prep.
- Has a POS (Square / Toast / Lightspeed / Shopify) or can export CSV.
- No data team, no analyst, no inventory manager. Limited technical patience.

### Secondary
**Small multi-location operators (2–10 sites)**
- Centralised planning, want per-location recommendations.
- Strategically important beyond their size: **higher willingness-to-pay** (value scales with sites, one decision-maker) and **within-account pooling** — a new site inherits its siblings' patterns immediately, with no cross-account data sharing involved (see §13).

> ⚠️ **Viability risk (named, not hidden):** single-location independents are the lowest willingness-to-pay segment in SaaS. The business case below (§17) must clear a low price ceiling. If it doesn't for a given customer, that customer should not be sold to — the tool will churn.

### Buying wedge and alternatives
Dial In must beat the way cafés already make this decision, not an empty market.

| Alternative | Why it exists | Why Dial In can win |
|---|---|---|
| Owner intuition / handwritten par sheets | Zero cost, trusted, fast | Breaks under weather/events and cannot learn from censored sellouts |
| POS reports / spreadsheets | Uses real sales history | Reports sales, not unmet demand; leaves the prep decision to the owner |
| Generic inventory tools | Broader operations footprint | Often optimises stock/accounting, not daily fresh-prep quantity under asymmetric cost |
| Enterprise demand planning | Strong modelling | Too heavy and expensive for an independent café or small group |

The wedge is narrow on purpose: **fresh-prep decisions for small operators where sellouts censor demand**. If a prospect mainly wants accounting, purchasing, or generic dashboards, Dial In is the wrong product. The first sales motion should be founder-led pilots with small multi-location operators and analytically curious independents; paid acquisition waits until §6.5 is proven.

---

## 6. Success Metrics

We separate **the metric we optimise**, **the outcomes we promise**, and **the adoption signals that tell us it's being used**. Conflating them is how prep tools lie to themselves.

### 6.1 Primary technical metric — what the model is judged on
- **Pinball loss (quantile loss) on held-out days**, evaluated at the café's operating quantile (configured per café; ≈0.78 in the §11.3 worked example).
- **Calibration:** of days flagged "high confidence", the realised demand should fall inside the stated range ≥ the stated rate (e.g. 80% range contains demand ~80% of the time).
- **Benchmark to beat:** a naive baseline of *last-week-same-weekday* and a *trailing 4-week same-weekday average*. If Dial In can't beat both on pinball loss, it ships nothing. This is the floor.

### 6.2 Business outcomes — what we promise the customer
These are **consequences of accuracy + the chosen service level**, not independent dials. They trade off along one curve; we move both only by tightening the forecast.

- **Waste reduction:** `prepared − sold` is the *upper bound* on waste, not waste itself — unsold units may be discounted, carried over (multi-day shelf life), or staff-eaten. True waste = `(prepared − sold) × (1 − salvage_share)`, measured on non-sellout days vs. the café's own pre-Dial-In baseline. For single-day-shelf items (croissants) `salvage_share ≈ 0` and the two coincide; for cookies it does not. `salvage_share` is the same per-category parameter that feeds `Co` in §11.3.
- **Stockout reduction:** measured as **sellout frequency** (`sold_out` days, §12 step 1), vs. baseline. Lost-sales *magnitude* is a modelled estimate (censored, §12), reported as a range, never a hard number.
- **Combined cost:** the honest headline — **total expected money lost per week** (waste COGS + estimated lost margin). One number, falls when either error shrinks.

> ⚠️ **We do not claim "reduce waste 15% *and* stockouts 20%" as independent guarantees.** With a fixed forecast they trade off. We claim: *reduce total expected cost of mis-prep by X%, with the waste/stockout split set by your configured risk preference.* Target for the combined cost reduction is set per café after a baseline period, not pulled from the air.

### 6.3 Adoption metrics — is it being used
- Weekly active usage > 80% of open days.
- Daily input completion > 90%.
- Median daily interaction < 30s; onboarding < 15 min.
- **Recommendation adherence rate** (the `adhered` flag, §10.4 — `prepared` within ±max(2, 10%) of the recommended prep point) — also a leading indicator of trust.

### 6.4 Model ship-gate (definition of done — when a café's model is allowed to drive prep)
A café's model graduates from shadow (§14) to live **only when all hold**, evaluated on that café's held-out days:
1. **Beats both naive baselines** (last-week-same-weekday, trailing-4wk same-weekday) on pinball loss at the operating quantile — by a margin outside noise (bootstrap CI excludes zero).
2. **Calibrated:** the stated p10–p90 range contains realised demand 75–85% of the time (not just ≥ a floor — over-wide ranges fail too).
3. **No systematic bias:** mean signed error within ±5% over the last 4 weeks (guards the chronic-under-prep loop, §12).
4. **Censoring rate observable:** if a category is sold-out on > 40% of comparable days, the upper quantile is flagged low-confidence and the de-censoring probe (§12) is active before the model is trusted on high-demand days.
Until all four hold, the café stays in shadow and the recommendation is advisory, not pre-filled as the default.

### 6.5 Pilot exit criteria — the business gate
The model gate is necessary but not enough. A pilot graduates to a paid offer only when the economics clear too:
1. **Data capture holds:** daily category input completion stays ≥90% on open days during the live pilot window. Below that, the product has an operations problem, not a modelling problem.
2. **Value is positive after uncertainty:** combined cost reduction vs. the café's own baseline has a confidence interval whose lower bound is above zero. If the interval crosses zero, the honest answer is "not proven yet."
3. **The value clears the intended price:** estimated monthly savings must support the target price at a value-capture ratio agreed before the pilot. The PRD cannot choose that ratio without a pricing decision; it must be set before any ROI claim is made.
4. **No hidden service-level trade:** stockout frequency cannot rise beyond the café's configured tolerance while waste falls. A cheaper-looking result that quietly accepts too many stockouts is a bad recommendation, not a win.

---

## 7. Core User Journey

The loop is **one event-driven action**: close out the day → the next day's recommendation appears instantly, readable from then on (evening, to prep overnight, or next morning). Available, not demanded.

### End of day — the single action
Operator enters today's numbers, then sees tomorrow's recommendation:
- **v1 (pre-POS):** type 5 numbers — `drinks_sold`, `sweet_sold`, `savory_sold`, `sweet_prepared`, `savory_prepared` (~30–60s).
- **post-POS:** POS supplies the `sold` figures; the operator confirms only `prepared` (pre-filled with the recommendation → one tap, ~10s).
- On submit, the engine runs and **tomorrow's recommendation renders immediately** — range, risk flag, one-line reason, optional "why" (3 drivers) — and persists.

### Any time after (read-only, ~15s)
- Reopen Dial In → see the stored recommendation for tomorrow. No recompute.

**Effort:** ~30–60s/day in v1 (manual), tightening to <30s post-POS. If the owner skips a day's entry, see §10.6 for graceful degradation instead of breakage.

---

## 8. MVP Scope

The MVP is deliberately the **rules-based version (V1, §11.1)** wrapped in the full decision and measurement machinery. We ship the *decision framing and the data discipline* first; model sophistication comes later.

In scope:
- **Daily recommendation engine** — per category (sweet / savory): recommended prep quantity, demand range, confidence, top 3 drivers.
- **Traffic forecast** — daily customer traffic proxied by **drinks sold** (chosen because drinks are effectively *uncensored* — espresso doesn't sell out the way fresh pastry does — so they are a clean leading signal of footfall; see §12).
- **Demand forecast** — sweet/savory demand from traffic forecast × attach rate, adjusted for weather, weekday, season, events.
- **Censored-demand correction** — distinguish true demand from sold-out sales (§12). In scope at MVP because without it the model trains on its own past mistakes.
- **Newsvendor service-level policy** — convert the demand distribution into a prep quantity using the café's configured cost ratio (§11.3).
- **Risk flag** — surface days where the recommended prep sits well below the upper demand band.
- **Recommendation & outcome logging** — every recommendation, the operator's actual prep, and realised sales, persisted for attribution (§14).

Explicitly **out** of MVP: ML models (V2), hourly/intraday forecasting, ingredient/staffing, multi-location benchmarking UI. (Roadmap §15.)

---

## 9. Data Collection Strategy

### Philosophy
Collection should be near-invisible. The owner should never feel like they are maintaining software. The end state is one manual number per day, pre-filled, everything else automated or imported. **v1 starts manual and earns its way down** as integrations land.

### Required daily input — v1 (pre-POS): manual
- **Drinks sold**, **sweet sold**, **savory sold**, **sweet prepared**, **savory prepared** (~30–60s). `prepared` always stays manual (the operator's decision); the `sold` figures are manual only until POS integration lands.

### Imported (POS integration — a later enhancement, not an MVP assumption)
- Drinks sold, sweet sold, savory sold (daily counts) — moves these out of manual entry once built.
- **Time of last sale per category** *(if the POS exposes timestamps)* — used to detect *when* a stockout happened. **If unavailable, all intraday claims are disabled** rather than faked (see §12 honesty note).

### Automatic (external feeds)
- **Weather (forecast + actual):** temperature, rainfall, wind, condition. We store both the *forecast we acted on* and the *actual that occurred*, because forecast error is itself a feature and a source of recommendation error (§11.4).
- **Calendar:** weekday, month, public holidays, school holidays, bridge days.
- **Seasonality:** month, quarter, tourism season.
- **Events (semi-manual at MVP, not fully automatic):** local markets, festivals, marathons, concerts, sporting fixtures, with an impact estimate. Hyperlocal events have no clean global API (§20 row 11), so MVP shows the owner a short candidate list to confirm in one tap; auto-feeds are added only where a reliable source exists.

---

## 10. Data Model

> Every table carries **`account_id`** (the login / tenant — the isolation boundary) and **`location_id`** (a site, which nests under an account; a multi-location operator owns several). The single-location café is the n=1 case. Two reasons this is non-negotiable: (1) `account_id` is what enforces that no café ever sees another's data (§10.7–10.8); (2) it lets a multi-location operator pool *within its own account* across sites, and lets the platform learn a shared weather/event benchmark *across* accounts — through model parameters only, never raw rows (§10.8, §13).

### 10.1 Operational demand tables
The UI starts with two categories (`sweet`, `savory`), but the storage grain is **account × location × date × category**. Hardcoding `sweet_*` and `savory_*` columns would make SKU-level prep (§15) a migration instead of a configuration change.

#### `daily_metrics` — one row per location-day
| Column | Notes |
|---|---|
| `account_id` | tenant / login — isolation boundary |
| `location_id` | site key (nests under `account_id`) |
| `date` | local business date, not UTC calendar date |
| `timezone` | needed for closeout, forecast horizon, and timestamped POS data |
| `is_open` | closure flag — closed days are excluded from training, not treated as zero demand |
| `drinks_sold` | traffic proxy; treated as near-uncensored except at observed throughput limits (§12) |
| `input_source` | `confirmed` / `corrected` / `imputed` (see §10.6) |
| `menu_version` | current menu/config version for regime-break handling |
| `recorded_at` | when the closeout was entered or imported |

#### `daily_category_metrics` — one row per location-day-category
| Column | Notes |
|---|---|
| `account_id`, `location_id`, `date` | joins to `daily_metrics` |
| `category` | MVP values: `sweet`, `savory`; later SKUs use the same grain |
| `sold` | observed units sold; censored by `prepared` |
| `prepared` | manual input; the censoring threshold |
| `sold_out` | derived boolean: did the category hit its prepared cap? |
| `stockout_detected_by` | `inferred_cap`, `pos_out_of_stock`, `manual`, or `unknown` |
| `time_last_sale` | nullable; only if POS provides timestamps |
| `salvage_share_observed` | nullable daily override when leftovers were discounted/carried over/staff-eaten |
| `input_source` | `confirmed` / `corrected` / `imputed` |

Primary keys are `daily_metrics(account_id, location_id, date)` and `daily_category_metrics(account_id, location_id, date, category)`.

### 10.2 `weather`
`account_id`, `location_id`, `date`, `temp_forecast`, `temp_actual`, `rain_forecast`, `rain_actual`, `wind`, `condition`, `forecast_made_at`.

### 10.3 `events`
`account_id`, `location_id`, `date`, `event_name`, `event_type`, `impact_score`, `source`, `confidence`.

### 10.4 `recommendations` *(new — the attribution backbone)*
| Column | Notes |
|---|---|
| `recommendation_id` | immutable id for audit and replay |
| `account_id`, `location_id`, `date`, `category` | one recommendation per category per target date |
| `recommended_prep` | what we told them to prep |
| `demand_p50`, `demand_p_lower`, `demand_p_upper` | the demand distribution, not just a point |
| `service_quantile` | the operating quantile used (e.g. 0.78) |
| `prepared` | what they actually prepped (joins to `daily_category_metrics`) |
| `adhered` | bool: `abs(prepared − recommended_prep) ≤ max(2, 0.10 × recommended_prep)` — measured against the **recommended prep point** (the `q*` quantity), not the demand range |
| `override_delta` | signed `prepared − recommended_prep` — magnitude/direction of override, for attribution analysis (§14) |
| `model_version` | which model/ruleset produced it |
| `input_snapshot_id` | hash/id of the inputs available when the recommendation was generated |
| `config_snapshot_id` | hash/id of economic settings and feature flags used |
| `generated_at` | |

> Without `recommendations` we can never prove Dial In caused an outcome — we'd be unable to separate the tool's advice from the owner's judgment or from the weather. This table is the attribution backbone.

### 10.5 `category_economics`
`account_id`, `location_id`, `category`, `retail_price`, `unit_cogs`, `salvage_share_default`, `attached_drink_margin`, `attach_and_balk_rate`, `service_quantile`, `effective_from`, `effective_to`.

This is where the business logic lives. `service_quantile` is computed from `Cu` and `Co` (§11.3), stored with effective dates, and copied into each recommendation so historical advice can be audited after prices or recipes change.

### 10.6 Data-quality / validation rules (enforced, not aspirational)
- **`sold ≤ prepared` always.** A violation means bad input or a POS mismatch → flag, don't ingest silently.
- **Counts are non-negative integers.** Fractional units, negative values, or missing category rows are rejected before they reach the model.
- **`sold_out` is derived, not trusted blindly.** Default rule: `sold ≥ prepared − ε` (§12). A POS out-of-stock event or manual correction can override it, but the override source is stored.
- **Missing daily input** → mark `input_source = imputed`, impute `prepared` from the recommendation, and *exclude that day from training the censoring logic* (we don't know the true cap). Never silently treat a skipped day as zero.
- **Closure days** (`is_open = false`) excluded from the demand series.
- **Regime breaks** — menu change, hours change, ownership change — flagged via a `menu_version` / config change event; the model down-weights pre-break history (§16).
- **Late corrections do not erase history.** They update the canonical row and append the before/after values to a `data_corrections` audit log, so model changes can be explained later without making every query version-aware.

### 10.7 Authentication & access (login-gated)
The app is **login-gated** — no anonymous access to data. Pattern mirrors the sibling `decant` app, deliberately, so we reuse what's already proven:

- **Auth:** `streamlit-authenticator` — per-user credentials, password **hashes** in `secrets.toml` (never plaintext, never committed), cookie-backed session with expiry. Supabase Auth is the upgrade path once we outgrow file-based credentials (self-serve signup, password reset, OAuth).
- **No guest mode for data.** Unlike decant's optional read-only guest, Dial In has nothing useful to show without an account's own history, so unauthenticated users hit the login wall and stop. A logged-out marketing/demo view (synthetic café) is a separate, read-only fixture — never real tenant data.
- **Session → tenant binding:** a successful login resolves to an `account_id`. Every data call in that session is scoped to it. The `account_id` is read from the server-side session, **never** from a client-supplied parameter.

### 10.8 Tenant isolation & training-data governance *(the part that reconciles the two requirements)*

> **Requirement:** historical data is **not shared between accounts**, **but** the platform may use it to train models. These coexist only if the *serving path* and the *training path* are separated and governed differently.

**Serving path — strict isolation (what a tenant can read):**
- Every query filters on the session's `account_id`. A café reads **only** its own rows. Enforced two ways (defense-in-depth, as decant does with its double-filter):
  1. **Application layer:** a single data-access module injects `WHERE account_id = :session_account_id` on every read/write — no raw table access anywhere else.
  2. **Database layer:** Postgres **Row-Level Security** on Supabase, keyed to the authenticated user or session-scoped account setting, so isolation holds even if app code has a bug. No real tenant data is loaded before this is working; a synthetic demo can prove the pattern first.
- **No cross-account reads in the product, ever.** Multi-location benchmarking (§15 Phase 6) compares locations **within the same `account_id`** only.

**Training path — what actually needs cross-account data, and what doesn't.**
We reject blanket "train on everyone's data". The model is split into three layers, governed differently, because the value of pooling is concentrated and decaying while the trust cost is permanent:

| Layer | What it estimates | Trains on | Why |
|---|---|---|---|
| **Core demand** (baseline level, attach rate, weekday shape) | the café's *identity* | **that café's own data only** (POS backfill at signup + ongoing) | High trust-sensitivity ("you're helping my rival"); pooling adds little once the café has ~8 weeks of its own history. No cross-account dependency. |
| **Environment response** (weather / event / seasonality elasticities) | generic physics, not identity | **pooled, anonymised, aggregate** across consenting accounts | A single café sees ~2–3 heatwaves and maybe one marathon a year — too few to estimate. The pool sees hundreds. Low trust-sensitivity. **This is the only genuine, lasting network effect.** |
| **Cold-start level prior** (for a brand-new café with *no* POS history) | a starting baseline before the café has data | **pooled, opt-in only**, conditioned on segment/country/footfall band | Needed only for the minority with no backfill (§20 row 4); decays to zero as the café's own data arrives. Wide ranges, Low confidence flag. |

- **Default is own-data + the shared environment layer.** Cross-account *level* pooling is **opt-in**, not opt-out — flipped from v2.0 on purpose. Most cafés never need it because their own POS backfill covers cold start.
- **Mechanics:** a **privileged offline training job** (platform service role, never a user session) fits the environment layer and the cold-start prior. It emits **parameters only** (elasticity coefficients, segment baselines) — never another tenant's raw rows, numbers, or name. A tenant benefits from others **solely as weights in the shared environment layer**.
- **Positioning to the customer:** the environment layer is sold as *"a benchmark built from cafés like yours,"* not *"we use your sales data."* Honest, and it's the framing customers accept.
- **Privacy posture:** training data is **operational counts** (pastries, drinks, weather, events) — no PII, low sensitivity. Residual memorisation risk (a near-unique café in a sparse segment) is bounded by training only on segments with **≥ N consenting accounts**; differential-privacy / k-anonymity is the hardening step for sparse segments — named, not built at MVP. [Likely sufficient given non-PII counts.]
- **Consent:** plain-language clause — *"your sales data is private to your account and is never shown to other customers. We use anonymised, aggregate patterns to improve the shared weather/event benchmark. You can opt out of contributing and still use the product."* Opt-out of the environment-layer contribution is allowed; opted-out accounts still *consume* the shared layer, they just don't feed it.

**Data-model additions to support this:**
- `accounts` table: `account_id`, `auth_subject`, `plan`, `contributes_to_shared_layer` (bool, default true), `cold_start_pool_opt_in` (bool, default **false**), `pos_backfill_months` (int — drives the §20 row 4 check), `created_at`.
- `locations` table: `account_id`, `location_id`, `name`, `timezone`, `city`, `country`, `open_days`, `service_capacity_hint`, `created_at`.
- `data_corrections` table: `account_id`, `location_id`, `date`, `category` nullable, `field_name`, `old_value`, `new_value`, `corrected_by`, `corrected_at`, `reason`.
- `account_id` FK on every operational table (done in §10.1–10.5).
- All cross-account aggregation goes through a separate `shared_layer_features` view readable by the **service role** and by **no tenant role**.

### 10.9 Data operations requirements
These are product requirements, not back-office niceties:

- **Lineage:** every recommendation stores `model_version`, input snapshot, economic config snapshot, weather forecast timestamp, and generation time.
- **Freshness:** after EOD submit, the next-day recommendation should render in the same session. If generation fails, the app shows the last valid recommendation with a clear stale flag.
- **Monitoring:** daily checks track missing input rate, validation rejects, sellout/censoring rate, calibration drift, weather forecast error, and cross-account access test results.
- **Reproducibility:** the model can replay any historical recommendation from stored inputs and config. If it cannot be replayed, it cannot be used in ROI attribution.
- **Access audit:** reads and writes of tenant data are logged with user, account, location, table, and timestamp. This matters more once multi-location accounts arrive.

---

## 11. Forecasting & Decision Strategy

The forecast produces a **demand distribution**. A separate, explicit **decision layer** turns that distribution into a prep quantity. Keeping them separate is the whole point.

**Cadence & horizon (a build decision, not a detail).** Generation is **event-driven, not a fixed clock**: when the operator submits the end-of-day numbers (§7), the engine runs and the **next day's recommendation is produced instantly** and persisted. The operator can read it from that moment — in the evening (to prep overnight) or the next morning. *Available, not demanded.* It relies on a **next-day weather forecast** (~12–36h horizon) — error propagated into the demand range (§11.4), forecast-vs-actual gap stored (§10.2) and monitored. A refresh re-runs if a materially newer weather forecast arrives before prep.

### 11.1 V1 — Rules-based (MVP)
- **Inputs:** weekday, month, weather forecast, attach rate, trailing same-weekday averages, event flags.
- **Point method (the mean):** expected demand = expected traffic (from drinks) × attach rate, with multiplicative weather/event/season adjustments from the **shared environment layer** (§10.8). Both the traffic model and the attach rate are fit on the café's **own censoring-corrected history** (§12). Attach rate must be computed from *de-censored* pastry demand, **not** raw `sold`; otherwise it is biased downward on exactly the sellout days, silently re-introducing the censoring we removed one level up (see §12).
- **Point → distribution (the part §11.3 needs).** A point forecast has no percentile, and the newsvendor decision needs one. Demand is a small integer count, so we model it as **Negative Binomial** — not Gaussian, and not Poisson (pastry demand is overdispersed; variance > mean). The mean comes from the point method; the dispersion is fit from historical forecast residuals within the same condition bucket (segment × weekday-band × weather-bucket). Where a bucket is thin, fall back to **empirical residual quantiles**. The recommendation is the `q*` quantile of this distribution (§11.3), rounded **up** (a fractional pastry is a whole pastry).
- **Demo vs. pilot boundary:** the synthetic demo may use the lighter comparable-day de-censoring method described in the companion design doc. A real pilot must either use the §12 censoring-aware method or stay in shadow until the lighter method passes the §6.4 ship-gate on that café's own held-out data. This prevents the demo shortcut from becoming an unexamined production shortcut.
- **Why first:** explainable, fast, stable, debuggable, and good enough to beat the naive baseline. Sophistication is not the bottleneck — data discipline, censoring correction, and the decision layer are. Cold-start prior only for no-backfill cafés (§13).

### 11.2 V2 — Machine learning *(only when data justifies it)*
- **Models:** gradient-boosted trees (LightGBM / XGBoost) and/or hierarchical models, applied **within the layer split** (§10.8): the **environment-response layer** is the natural place for a pooled cross-café model (lots of data, low sensitivity); the **core demand layer** stays per-café (or per-account for multi-location), with shrinkage only toward that account's own sites.
- **Hard precondition:** a single café generates **~250–320 usable rows per year** (≈6 open days/week). Tree models with 25–35 features on a few hundred rows overfit badly — so a café-private ML core is only justified once that café beats both the V1 rules model **and** the naive baseline on held-out pinball loss. Until then V1 rules + the pooled environment layer is the default. [Certain — data-volume constraint, not a preference.]
- **Features:** §13 signals + censored-corrected demand labels.

### 11.3 V3 — Probabilistic forecasting + the newsvendor decision *(the core, not a nice-to-have)*
The recommendation is **not** the mean or median forecast. Prep is a **newsvendor decision**: choose the quantity that minimises expected cost given asymmetric over/under costs.

```
Optimal service level  q*  =  Cu / (Cu + Co)

  Cu = under-prep cost = lost pastry margin
                       + (attach-and-balk rate × attached-drink margin)
                       e.g. €2.60 + 0.4 × €1.50 ≈ €3.20
  Co = over-prep cost  = waste cost per unsold unit − salvage value
                       e.g. €0.90 − €0.00 = €0.90   (raise salvage if
                       unsold stock is discounted, carried over, or staff-eaten)

  q* = 3.20 / (3.20 + 0.90) = 0.78

→ Recommend the ~78th percentile of the demand distribution, not the mean.
```

Two corrections over a naive newsvendor, both flagged because they materially move `q*`:
- **`Cu` includes the attached drink, not just the pastry** — consistent with §2, where a stockout also costs the coffee that would have ridden with it. The `attach-and-balk rate` is the share of stocked-out pastry buyers who also abandon a drink purchase; estimated per café, conservative default.
- **`Co` is net of salvage** — a binned croissant costs full COGS; a discounted or staff-eaten one costs less. Items with multi-day shelf life (cookies) have high salvage and a much lower `q*`.

Interpretation for the owner (never shown the maths): *"because running out costs you more than throwing out, we tell you to make a bit extra — the amount that loses you the least money over time."* `Cu`, `Co`, attach-and-balk, and salvage are configured per café at onboarding (sane defaults), and surfaced as a single **"waste vs run-out" slider** the owner can nudge by feel.

### 11.4 Uncertainty propagation (honesty layer)
The demand range must include error from the **forecasted inputs**, not just demand noise — we predict demand from *forecast* weather and *estimated* events, both of which are wrong sometimes. On days with volatile or low-confidence inputs (uncertain storm, ambiguous event), the range **widens** and confidence drops. The model is allowed to say "I don't know — make your usual ±20%."

---

## 12. Handling Censored Demand *(the central estimation problem)*

> This is not a footnote. It is the reason naive forecasting fails at this problem, and the main thing that makes Dial In defensible.

### The trap
Sales ≠ demand. If you prep 40 and sell 40, you sold out — true demand could be 45, 60, or 70; you can't see it. If you train a forecaster on raw `sold`, it learns **supply-constrained sales**, recommends prep ≈ past sold ≈ past prepared, and the demand ceiling is *never discovered*. Under-prep looks "accurate" (you sold everything!) and the model quietly repeats yesterday's mistake forever. **A forecaster that ignores censoring converges to the café's existing error.**

### The correction
1. **Label each day censored or uncensored — with a defined threshold.** The `sold_out` flag is set when `sold ≥ prepared − ε`, where `ε` is a small per-category tolerance (default **1 unit**, configurable) absorbing crumbs/miscounts. Where the POS emits a true out-of-stock event, that overrides the inferred flag. Uncensored = leftovers existed (`sold < prepared − ε`) → demand observed exactly. Censored = `sold_out` → demand is *at least* `prepared`. **This threshold is load-bearing**: too tight and we miss real sellouts, too loose and we treat normal days as censored. It is tuned per café and audited (§6.1 calibration).
2. **Estimate true demand on censored days** from uncensored comparable days (same weekday band, weather bucket, traffic level, event status) plus the **drinks-sold traffic signal** and the category attach rate. Drinks reveal footfall even on days pastries sold out.
3. **Fit with a censoring-aware method.** **Primary: a Tobit (Type-I, right-censored) model on log-demand**, with the sellout flag (§12 step 1) marking the censored observations; a survival/Kaplan-Meier framing is the cross-check on the upper tail. Never ordinary regression on `sold`. [Certain on the framing; Tobit is the committed default, revisited only if it underperforms the cross-check on pilot data.]
4. **Report the consequence honestly:** estimated lost units and lost margin on sold-out days, as a **range**, feeding the combined-cost metric (§6.2). Never a spuriously precise "you lost exactly 12 sales."

### When the correction is weak — and what we do about it
Censoring-correction is not magic: **it cannot recover a tail it has never observed.** A café that *chronically* sells out has almost no uncensored high-demand days, so the upper quantile (`q*`, §11.3) is **extrapolated, with wide error — exactly on the high-demand days that matter most.** Three responses, in order:
1. **Detect it.** Track each category's **censoring rate** (share of days sold out). Above a threshold (e.g. >40% of comparable days), flag the upper-quantile estimate as low-confidence.
2. **Widen, don't fake.** When the tail is unobserved, the demand range widens and confidence drops (§11.4) rather than emitting a confident extrapolation.
3. **De-censor by design — the principled move.** The recommendation deliberately preps **above** recent sellout levels on a small, controlled share of low-risk days to *observe* where demand actually tops out. This is active experimentation to learn the tail, with the extra-waste cost bounded and disclosed. It is the only way a chronically-under-prepping café ever discovers its true ceiling, and it is the difference between a tool that breaks the under-prep loop and one that merely re-fits it.

### A caveat on the traffic proxy
"Drinks are uncensored" holds on ordinary days but **breaks on peak days**: a single barista, a long queue, and walk-outs (balking) mean drink sales are **throughput-censored** on the busiest days — the same days the recommendation cares about most. We therefore (a) treat very-high-traffic days as potentially censored on the drinks side too, and (b) lean on external footfall signals (weather, events, day-of-week) rather than drinks alone when traffic approaches the café's observed service ceiling. [Likely material for high-volume cafés.]

### Honesty note on intraday
The "sold out at 11:15, demand continued to 14:00" story requires **timestamped sales**. If the POS provides `time_last_*_sale`, we estimate the lost-sales tail from the remaining-hours traffic curve. If it does not, **we disable that claim** and fall back to day-level censoring only. We do not invent intraday detail the data can't support.

---

## 13. Forecast Features & Cold Start

### Feature families
- **Traffic:** drinks sold (today/lag-1d/lag-7d), rolling 4-week same-weekday mean, attach rate (pastries per drink) and its stability.
- **Weather:** temp, rain, wind, condition, outdoor-seating viability; both forecast and actual stored.
- **Events:** market days, marathons, festivals, concerts, fixtures — with impact and source confidence.
- **Calendar/season:** weekday, month, quarter, public/school holidays, bridge days, tourism season, Christmas period.

### Cold start — and why it's smaller than it looks
The instinct is "a new café has zero rows, so it must borrow from other cafés." Mostly false. **Most cafés arrive with 1–2 years of their own POS history** (Square/Toast/Lightspeed retain it). We backfill it at signup, so the median new café trains its **own** core model from day one — no other account's data required. Cold start is a minority problem, not the default. [Likely — gated on POS export coverage, §20 row 4.]

What actually drives the recommendation, by situation:

| Situation | Core demand (level/attach) | Environment response (weather/event) | Confidence |
|---|---|---|---|
| **Has POS backfill** (the common case) | café's **own** backfilled history | shared environment layer (§10.8) | Medium→High from day 1 |
| **No backfill, 0–8 weeks** | **opt-in** cold-start prior (segment/country/footfall band) + 3-question setup, shrinking toward own data as it arrives | shared environment layer | Low; ranges wide |
| **8+ weeks, any café** | café-specific dominates | shared environment layer (still pooled — café never sees enough rare events alone) | High |

Two things never change regardless of history: (1) the **environment-response layer is always shared** — a café with three months of data still can't estimate its own heatwave or marathon elasticity, so the pool carries it permanently; (2) the **core baseline stays café-private**.

This is why `account_id`/`location_id` are mandatory (§10). The cross-café benefit flows **only through shared parameters** (§10.8) — a new café inherits an *elasticity* or an opt-in *prior*, never another café's actual rows. Tenant isolation and pooling aren't in conflict; they live on opposite sides of the serving/training split, and the only data that crosses the boundary is the low-sensitivity environment layer.

---

## 14. Measurement & Attribution Design *(how we prove it works)*

A data tool that can't prove its own impact is a liability. Plan:

1. **Baseline period (2–4 weeks):** run in shadow mode — generate recommendations, log them, but the owner preps as usual. Establishes the café's own pre-Dial-In waste, sellout frequency, and combined cost. *Note the friction trade-off:* in shadow there is no acted-on recommendation to pre-fill the EOD input (§7), so `prepared` must be entered manually and completion will dip during exactly the period we need clean baseline data. Mitigate by pre-filling the shadow input with the café's own trailing same-weekday prep and keeping the baseline short.
2. **Naive baseline benchmark:** the model must beat last-week-same-weekday and trailing-4-week-same-weekday on pinball loss before it is allowed to influence decisions (§6.1).
3. **Staged rollout as a quasi-experiment — stated honestly.** Cafés move from shadow to active on a staggered schedule; the still-shadow cohort acts as a moving control for seasonality and macro shocks. This is a **true stepped-wedge only if switch-on order is randomised**; if order is driven by signup date or sales motion it is a convenience rollout with selection bias (early adopters differ), and we treat the cross-café comparison as suggestive, leaning on the within-café pre/post and adherence-conditioned readout (#4) for the real signal. We randomise switch-on order where operationally possible.
4. **Adherence-conditioned readout:** because `recommendations.adhered` is logged, we can compare outcomes on days the owner followed the recommendation vs. days they overrode it — the cleanest within-café causal signal we can get without a formal experiment.
5. **Headline impact metric:** change in **total expected cost of mis-prep per week** (waste COGS + estimated lost margin), reported with a confidence range, never as a bare percentage.

### 14.1 Pilot measurement protocol
Before the first real pilot starts, write down:
- **Target price or price band** being tested, so ROI is judged against a real commercial bar (§6.5), not a moving one.
- **Baseline window and live window.** Default is 2–4 weeks shadow plus at least 4 weeks live, extended if closures/events leave too few usable open days. This is not a formal power guarantee; it is the minimum evidence window before making a commercial claim.
- **Customer-configured tolerance:** the owner chooses the waste/run-out preference through the economics setup (§10.5, §11.3). We do not call a recommendation "better" if it violates that preference.
- **Attribution view:** report three numbers together — observed waste proxy, sellout frequency, and combined expected cost. Reporting only the best-looking one is cherry-picking.
- **Decision log:** every override gets an optional reason (`weather felt wrong`, `supplier issue`, `large order`, `owner judgement`, `other`). Overrides are signal, not failure; they tell us what the model missed.

---

## 15. Future Roadmap
- **Phase 2 — Intraday:** hourly demand curves and sellout-time prediction (gated on timestamped POS data).
- **Phase 3 — Staffing:** convert traffic forecasts into shift suggestions.
- **Phase 4 — Ingredients:** explode category prep into raw inputs (butter, flour, chocolate) via recipe mapping.
- **Phase 5 — Inventory optimisation:** ordering and par levels.
- **Phase 6 — Multi-location benchmarking:** league tables and best-practice transfer across a customer's sites.
- **Phase 7 — SKU-level prep:** move from sweet/savory categories to individual products (croissant vs pain au chocolat). *Named explicitly because category-level is an MVP simplification, not the end state — within-category allocation is much of the real decision, and customers will ask for it.*

---

## 16. Edge Cases & Regime Changes
- **Closures / holidays:** `is_open = false`; excluded from the series.
- **Menu changes:** new/removed product → `menu_version` bump; pre-change history down-weighted for affected categories.
- **Hours changes / ownership changes:** treated as regime breaks — pre-break history down-weighted and ranges widened; if the break invalidates most history, fall back to the cold-start path (§13: own remaining data + shared environment layer, opt-in prior only if truly no usable history).
- **Bad manual input:** caught by the `sold ≤ prepared` rule (§10.6); flagged for one-tap correction.
- **POS outage / missing import:** fall back to traffic priors; mark confidence Low.

---

## 17. Business Case & Pricing (sizing the value before building)

> The product only makes sense if the money saved clears a price a low-WTP segment will pay. Illustrative back-of-envelope — *numbers are placeholders to be replaced with real customer data, the framework is the point.* [Guessing on the numbers, Certain on the method.]

**Size the addressable pool first, then apply a single forecast-driven reduction — do not add two independent savings (that would double-count the tradeoff in §6.2).**

Baseline monthly **cost of mis-prep** for an example single-location café (preps ~80 pastries/day):

| Component of mis-prep cost | Baseline (illustrative) |
|---|---|
| Waste: ~12 units/day discarded @ €0.90 COGS × 30 | ~€324 |
| Lost margin: ~8 sellout days × ~10 unmet units @ €2.60 | ~€208 |
| **Total addressable mis-prep cost** | **~€532/mo** |

A better forecast shrinks the **whole** waste↔stockout curve inward; the newsvendor quantile (§11.3) only chooses *where on the curve* the café sits (more waste vs more stockout), it doesn't reduce the total — **accuracy does.** A credible combined reduction of **20–30%** on the €532 pool → **~€105–160/mo** saved. AOV uplift (the attached coffee on a recovered pastry sale) is real upside, deliberately left unsized.

→ Implied SaaS price ceiling **≈ €40–80/mo** at a sane value-capture ratio. Multi-location operators clear it far more comfortably (value scales with sites, one decision-maker). **Implication:** lead go-to-market with small multi-location operators; single-location is volume, not margin. The 20–30% reduction is itself an assumption to validate against the shadow-period baseline (§14), not a promise.

### 17.1 Pricing validation checklist
The current pricing logic is a framework, not evidence. Before quoting a price from it, collect:
- Actual daily prep, sold, and leftover handling by category.
- Retail price, unit COGS, salvage behaviour, and attached-drink margin.
- Number of open days, sellout days, and owner-estimated missed demand.
- Whether the buyer values saved owner attention, staff stress reduction, and better customer experience enough to pay for them; if not, leave them out of ROI.
- The buyer type making the decision: owner-operator, operations manager, or multi-site owner. The same euro saving has different buying friction for each.

---

## 18. UX Requirements
- **Mobile first.** Owners use a phone, often one-handed, mid-service.
- **Fast.** Page load < 3s; the recommendation is the first thing rendered.
- **Simple.** No dashboard or report on the landing screen; no analytics jargon. The "why" is one tap deep, not in the owner's face.
- **Honest UI.** Confidence and range are always shown — a single number with no range is forbidden, because it implies certainty the model doesn't have.

---

## 19. Non-Goals
Dial In is explicitly **not**: an inventory system · an accounting system · a POS replacement · a workforce-management platform · a BI / general reporting tool · a recipe manager.

It does **one** job: tell an independent café how much fresh food to prep, and prove it was right.

---

## 20. Open Questions & Assumptions Register
| # | Assumption / open question | Risk if wrong | How we'll close it |
|---|---|---|---|
| 1 | Drinks sold is a reliable, near-uncensored traffic proxy | Whole traffic→demand chain weakens | Validate attach-rate stability on pilot data before trusting it |
| 2 | Owners will enter `prepared` daily | Censoring logic degrades | Pre-fill + one-tap confirm; monitor completion; degrade gracefully |
| 3 | Per-café `Cu`/`Co` can be captured at onboarding | Wrong service level → systematic mis-prep | Sane category defaults; let owners tune by feel ("waste vs run-out" slider) |
| 4 | **Most signups have exportable POS backfill (1–2 yrs)** — the assumption that kills most cold start | If <~70% have backfill, cross-account cold-start pooling matters far more than §13 claims | Measure `pos_backfill_months` on first cohort; if low, reconsider opt-in default on the cold-start prior |
| 5 | Shared environment layer beats per-café weather/event estimation | If café-level rare-event signal is good enough alone, the only lasting network effect disappears | Compare pooled-elasticity vs café-only on held-out rare-condition days |
| 6 | Single-location WTP clears the price ceiling | Churn, bad unit economics | Validate §17 with real pilot economics before scaling that segment |
| 7 | GUC-based RLS works cleanly with `streamlit-authenticator` before Supabase Auth | If not, tenant isolation design needs rework before real data | Prove with synthetic demo: app role, `SET LOCAL app.current_account_id`, and cross-account query tests |
| 8 | Customers accept the shared environment layer when framed as a benchmark | Trust pushback; contribution opt-outs shrink the pool | Plain-language clause + `contributes_to_shared_layer` opt-out (still consume, don't feed); monitor opt-out rate |
| 9 | Shared layer won't memorise sparse segments | Indirect leakage of a near-unique café | Train shared layer only on segments with ≥ N consenting accounts; DP/k-anonymity for sparse segments |
| 10 | POS timestamps available often enough for intraday | Phase 2 (hourly) blocked | Survey POS timestamp coverage in pilot cohort |
| 11 | Hyperlocal events can be sourced as an "automatic" feed | §9 oversells; no clean global API for a town-square market | Treat events as semi-manual at MVP (owner confirms a short list); auto-feed only where a reliable source exists; size coverage before promising |
| 12 | Chronic-sellout cafés will tolerate the de-censoring probe (occasional deliberate over-prep) | The tail-learning mechanism (§12) is rejected by waste-averse owners | Make probe opt-in, bounded, and framed as "we'll occasionally test a bit higher to find your real ceiling"; cap added waste |
| 13 | Fadri's real operating bands are close enough to seed a credible synthetic demo | Fake-looking data will hurt trust before the product is discussed | Get rough drinks/day, attach, waste, and sellout ranges; if unavailable, label Fadri as fictionalised and do not imply realism |
| 14 | Category-level recommendations are enough for MVP | Owners may ask "which pastry?", not just "how many sweet?" | Track override reasons and sales mix; promote SKU-level prep only if category advice is too blunt |
| 15 | The simplified demo de-censoring method is close enough to show behaviour | Demo teaches the wrong model habit | Keep it synthetic-only; real pilot must pass §6.4 before live recommendations |
| 16 | The owner can supply or approve economics inputs | `q*` becomes a fake precision number | Store defaults separately from confirmed values; show confidence lower until confirmed |

---

## 21. Build Readiness Gates
This is the checklist that moves the PRD from an interesting idea to something a principal DA would be comfortable piloting:

1. **Schema gate:** account/location/category grain implemented; RLS test passes; `recommendations` stores lineage and economics snapshots.
2. **Data gate:** validation rejects bad counts; missing inputs are imputed but excluded from censoring training; corrections are audited.
3. **Model gate:** rules model beats both naive baselines on pinball loss, is calibrated, and shows no systematic bias (§6.4).
4. **Business gate:** pilot economics clear the price bar with uncertainty shown (§6.5, §17.1).
5. **Honesty gate:** all claims separate observed facts, modelled estimates, and synthetic/demo behaviour.

Failing any gate does not kill the product. It tells us what problem we actually have: data capture, model quality, tenant safety, or business value.

---

## 22. Positioning
Dial In helps independent cafés decide what to prepare tomorrow — combining the owner's instinct with a model that respects how their money actually works: running out costs more than throwing out, and you can't manage what you can't measure.

**"What should we prepare tomorrow?"** Everything else is secondary.
