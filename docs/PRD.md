# Dial In — Product Requirements Document (PRD)

**Version:** 1.3
**Author:** Tomasz Solis
**Status:** Draft
**Created:** 2026-05-31
**Last updated:** 2026-06-01
**Companion:** `2026-05-31-synthetic-data-and-demo-design.md` (demo/generator design; v1 input & cadence reconciled here)
**Project Type:** Learning project / decision-support webapp / Fadri-ready demo
**Current Target:** Synthetic demo account first; Fadri Café real-data account once data is available

> **TL;DR** — Dial In is currently a learning project and demo webapp, not a product being prepared for sale. The goal is to learn Docker/Postgres, synthetic data generation, demand forecasting, uncertainty, and decision-making under asymmetric costs. The app answers one operational question for a mixed-focus specialty coffee place: *how much fresh vegan sweet/savory food should we prep for tomorrow?* The hard part is not just predicting sales — sales are **censored** when food sells out, and the cost of running out is not equal to the cost of waste. Dial In treats prep as a **newsvendor decision**: forecast the demand *distribution*, then pick the prep quantity that minimises expected cost given the café's margin and waste economics. The first complete version has a login-gated synthetic demo account; the second real-data path is a Fadri Café account once data is available.

---

## 1. Executive Summary

Dial In is being built first as a hands-on learning project and practical demo for a real
specialty coffee context. It is not currently planned as a product to sell. A commercial SaaS
could be an optional future path, but it is not the goal driving today's decisions.

The learning goals are concrete:
- learn Docker and local Postgres development;
- model demand with synthetic and later real café data;
- understand censored demand, uncertainty, and calibration;
- turn forecasts into decisions rather than dashboards;
- improve confidence and accuracy step by step without overclaiming.

The intended finished webapp has two account types:
- **Demo account:** generated synthetic data with weather, events, seasonality, sellouts,
  waste, and clear observed/truth separation.
- **Fadri Café account:** same app constraints and decision flow, but powered by real Fadri
  data once available.

### 1.1 Production To Do - Non-Real Forecast Inputs

Before Dial In is used as a daily operating tool for a real cafe, every non-real input that
can affect a recommendation must be replaced with a real source, confirmed by the owner, or
clearly labelled as demo/advisory. This is a product requirement, not just documentation.

Open production work:
- **Weather:** demo weather is generated, not pulled from a weather API. Production needs a
  real forecast and historical actuals provider, stored with forecast timestamps, actual
  observed timestamps, stale-data detection, and a seasonal-normal fallback that lowers
  confidence.
- **Usage and adherence:** demo closeouts, recommendation adherence, overrides, and health
  rates are synthetic until real operators use the app. They cannot be used as adoption,
  adherence, or ROI evidence.
- **POS sales and traffic:** generated drinks/category sales are placeholders for POS import
  or owner-entered closeout data. Production must audit import rejects, re-import changes,
  missing days, and corrections before those rows feed recommendations.
- **Events, holidays, and tourism season:** generated events and configured seasonal lifts
  must be replaced with confirmed calendars, owner-approved local events, or clearly marked
  assumptions. Unconfirmed events should reduce confidence rather than silently lift demand.
- **Economics:** category prices, COGS, salvage, attached-drink margin, and stockout-cost
  assumptions are defaults until owner-confirmed. Recommendations using defaults must stay
  advisory/lower-confidence.
- **Opening hours, closed days, and menu versions:** demo defaults must become real operating
  hours, closure review, and menu/regime-break markers so comparable history is not polluted.
- **Replay, savings, and scorecards:** synthetic replay is not proof of business impact. Real
  value claims require held-out real data, baseline comparison, calibration checks, and the
  model gates in Section 6.4.

Independent cafés decide food prep by gut. The decision is high-frequency (daily), irreversible
(fresh food can't be un-baked), and asymmetric (running out costs more than throwing out).
Owners get it wrong in both directions and often have no time to analyse why.

Dial In recommends a daily prep quantity per product category, with a demand range and the reasons behind it. The operator closes out the day's numbers and the next day's recommendation appears instantly, readable that evening or the next morning. It uses sales history, weather and event forecasts, and seasonality. In **v1 the day's numbers are entered manually** (~30–60s); once POS integration lands, `sold` is auto-imported and daily effort drops toward the <30s / one-input target.

Three things separate Dial In from "a forecast in an app":

1. **It optimises a decision, not an accuracy score.** The output is the prep quantity that minimises expected money lost — explicitly trading waste cost against stockout cost — not the most likely sales number.
2. **It corrects for censored demand.** It distinguishes "sold 40 because demand was 40" from "sold 40 because we only made 40 and ran out", and learns from both correctly.
3. **It is measurable.** Every recommendation, the operator's actual decision, and the realised outcome are logged, so impact can be attributed rather than asserted.

---

## 2. Problem Statement

Independent cafés rely on intuition to decide daily prep. Intuition breaks down under variance: weather swings, tourism, local events, seasonality, and weekday/weekend differences each move demand by amounts an owner can't hold in their head simultaneously.

The first wedge is more specific than "any coffee shop." It is a specialty coffee place where
fresh vegan sweet/savory goods are a meaningful part of the offer, often baked by the
operator, and where weekend demand regularly exceeds prep. A concrete target scenario: open
09:00–13:00, food sold out by about 11:30, then the shop spends the last 1.5 hours selling
coffee only. That is not just an accuracy problem; it is a missed basket-size and customer
experience opportunity balanced against the real cost of over-baking.

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

## 3. Project Vision

Dial In should become a small, usable decision-support webapp for fresh-food prep. The first
version proves the workflow on synthetic data. The Fadri version should later run the same
workflow on real data.

When the operator closes out the day, the next day's recommendation appears — readable that
evening (to prep overnight) or the next morning — and reads like a weather forecast, just as
quick to consume:

**Example recommendation:**
- **Expected traffic:** 190–220 drinks
- **Recommended prep:**
  - Sweet pastries: **54** (demand range 46–61, prep set at the ~78th percentile per §11.3)
  - Savory pastries: **31** (demand range 25–36)
- **Risk flag:** High demand likely — sunny Saturday + local market
- **Confidence:** High (similar to 18 comparable past days)

The operator absorbs everything in under 30 seconds and gets on with their day.

---

## 4. Project Principles

1. **Low friction beats marginal accuracy.** A good-enough model used every day beats a great model that needs babysitting. Owner effort budget: **< 30 seconds/day, < 15 minutes onboarding** — a **post-POS target**. In **v1 (pre-POS), input is manual** (drinks + sweet/savory sold + sweet/savory prepared, ~30–60s); the budget tightens once POS auto-supplies `sold` (see §9).
2. **Every manual input must justify itself — and be protected.** `prepared` is the input that can never be automated, because it is the only way to detect a stockout; in v1 the operator also enters `sold` until POS integration lands. Because the model leans on these, we validate them, not just request them (see §10.6).
3. **Recommend, don't report.** The default screen is a decision, not a dashboard. Analytics exist, but never on the landing screen.
4. **Optimise expected money, not forecast error.** Forecast accuracy is a means; the end is the prep quantity that loses the least money given this café's economics.
5. **Be honest about uncertainty.** When the model is guessing (new café, volatile weather, unusual event), it says so and widens the range rather than faking a confident number.

### 4.1 Deployment & database architecture
Dial In is **Postgres-first and provider-neutral**. The product requirement is not Supabase, Neon, or any specific vendor; it is a relational Postgres database with tenant isolation, recommendation/outcome logging, and a clean synthetic observed/truth split.

| Target | Role | Notes |
|---|---|---|
| **Local Docker Postgres 17** | Default development database | Used for schema work, migrations, generator development, tests, and replay when running locally. |
| **Neon free Postgres** | Hosted Streamlit demo database | Needed when the app runs on Streamlit Community Cloud, because the hosted app cannot use a database running on a laptop. Demo/Fadri path only for now. |
| **Supabase Postgres** | Compatible future target | Acceptable if we later need Supabase features, but the app must not depend on Supabase client APIs or Supabase Auth. |
| **Paid managed Postgres** | Optional future production option | Not needed for the learning/demo goal; only reconsider if real usage outgrows free/local infrastructure. |

The app reads its database connection from `DATABASE_URL`. Local development can point that variable at Docker Postgres; a live Streamlit demo points it at Neon with `sslmode=require` stored in Streamlit secrets. Migrations and seed jobs use a separate owner/admin connection, not the low-privilege app connection.

Neon is therefore the chosen **hosted demo provider**, not the architecture. Neon Auth stays off. `streamlit-authenticator` remains the login-gated demo pattern until there is a concrete reason to adopt managed auth.

Docker is part of the development plan, not a prerequisite for the first hosted demo. The Docker setup should be added in a later implementation pass as a small local Postgres practice path: `docker-compose.yml`, `.env.example`, migrations, and a simple migration command that runs through the container.

---

## 5. Target User And Fit

### Primary current fit
**Mixed-focus specialty coffee places that bake meaningful sweet/savory goods**
- 1 location, 2–10 staff, owner-operated, significant fresh-food prep.
- Best early fit: mixed-focus specialty coffee places that also bake meaningful sweet and savory goods, especially where weekend sellouts are common.
- Weaker fit: coffee-first shops where cookies or packaged snacks are a small nice-to-have and food sellouts do not materially change revenue, customer experience, or owner stress.
- Has a POS (Square / Toast / Lightspeed / Shopify) or can export CSV.
- No data team, no analyst, no inventory manager. Limited technical patience.
- Current real-world target: friends/Fadri-style specialty coffee context where vegan sweet
  and salty goods are baked in-house and sellout timing is a real operational pain.

### Secondary future fit
**Small multi-location operators (2–10 sites)**
- Centralised planning, want per-location recommendations.
- Strategically important beyond their size: **higher willingness-to-pay** (value scales with sites, one decision-maker) and **within-account pooling** — a new site inherits its siblings' patterns immediately, with no cross-account data sharing involved (see §13).

> Note: this is not a sales plan today. The fit filter still matters because a learning project
> can drift into solving a fake problem. If food is incidental, Dial In may be technically
> interesting but operationally unimportant.

### Buying wedge and alternatives
Dial In must beat the way cafés already make this decision, not an empty market.

| Alternative | Why it exists | Why Dial In can win |
|---|---|---|
| Owner intuition / handwritten par sheets | Zero cost, trusted, fast | Breaks under weather/events and cannot learn from censored sellouts |
| POS reports / spreadsheets | Uses real sales history | Reports sales, not unmet demand; leaves the prep decision to the owner |
| Generic inventory tools | Broader operations footprint | Often optimises stock/accounting, not daily fresh-prep quantity under asymmetric cost |
| Enterprise demand planning | Strong modelling | Too heavy and expensive for an independent café or small group |

The wedge is narrow on purpose: **fresh-prep decisions for small operators where sellouts
censor demand and fresh food is operationally meaningful**. If a user mainly wants accounting,
purchasing, generic dashboards, or only sells coffee with incidental snacks, Dial In is the
wrong tool. A commercial go-to-market motion is explicitly optional future context, not the
current objective.

---

## 6. Learning, Model, And Usefulness Metrics

We separate **the metric we optimise**, **the outcomes we estimate**, and **the usage signals
that tell us the workflow is viable**. Conflating them is how prep tools lie to themselves.
Because this is currently a learning/Fadri demo project, these metrics are learning gates and
usefulness checks, not sales promises.

### 6.1 Primary technical metric — what the model is judged on
- **Pinball loss (quantile loss) on held-out days**, evaluated at the café's operating quantile (configured per café; ≈0.78 in the §11.3 worked example).
- **Calibration:** of days flagged "high confidence", the realised demand should fall inside the stated range ≥ the stated rate (e.g. 80% range contains demand ~80% of the time).
- **Benchmark to beat:** a naive baseline of *last-week-same-weekday* and a *trailing 4-week same-weekday average*. If Dial In can't beat both on pinball loss, it ships nothing. This is the floor.

### 6.2 Operational outcomes — what we estimate
These are **consequences of accuracy + the chosen service level**, not independent dials. They trade off along one curve; we move both only by tightening the forecast.

- **Waste reduction:** `prepared − sold` is the *upper bound* on waste, not waste itself — unsold units may be discounted, carried over (multi-day shelf life), or staff-eaten. True waste = `(prepared − sold) × (1 − salvage_share)`, measured on non-sellout days vs. the café's own pre-Dial-In baseline. For single-day-shelf items (croissants) `salvage_share ≈ 0` and the two coincide; for cookies it does not. `salvage_share` is the same per-category parameter that feeds `Co` in §11.3.
- **Stockout reduction:** measured as **sellout frequency** (`sold_out` days, §12 step 1), vs. baseline. Lost-sales *magnitude* is a modelled estimate (censored, §12), reported as a range, never a hard number.
- **Combined cost:** the honest headline — **total expected money lost per week** (waste COGS + estimated lost margin). One number, falls when either error shrinks.

> ⚠️ **We do not claim "reduce waste 15% *and* stockouts 20%" as independent guarantees.** With a fixed forecast they trade off. For now, the honest target is: *estimate total expected cost of mis-prep, explain the waste/stockout tradeoff, and learn whether recommendations would have improved decisions.* Any savings number is an estimate with assumptions, not a promise.

### 6.3 Workflow metrics — is it usable
- Weekly active usage > 80% of open days.
- Daily input completion > 90%.
- Median daily interaction < 30s; onboarding < 15 min.
- **Recommendation adherence rate** (the `adhered` flag, §10.4 — `prepared` within ±max(2, 10%) of the recommended prep point) — also a leading indicator of trust.

### 6.4 Model ship-gate (definition of done — when a café's model is allowed to drive prep)
A café's model graduates from shadow (§14) to live **only when all hold**, evaluated on that café's held-out days. These are full ship gates, not claims that a four-week pilot can prove everything:
1. **Minimum evidence first:** enough held-out open days exist to evaluate the category honestly. For a short Fadri window, these checks are diagnostics; they do not become a hard statistical pass/fail until the sample is large enough to make the result meaningful.
2. **Beats both naive baselines** (last-week-same-weekday, trailing-4wk same-weekday) on pinball loss at the operating quantile — by a margin outside noise when the sample supports that test.
3. **Calibrated:** the stated p10–p90 range contains realised demand about 75–85% of the time once enough held-out days exist. Before that, calibration is reported as directional evidence with wide uncertainty, not a pass badge.
4. **No systematic bias:** mean signed error is tracked over the most recent usable window and must not show chronic under-prep (§12). The ±5% target is a mature-data target, not something a tiny pilot can estimate tightly.
5. **Censoring rate observable:** if a category is sold-out on > 40% of comparable days, the upper quantile is flagged low-confidence and the de-censoring probe (§12) is active before the model is trusted on high-demand days.
Until the gates are met with enough data, the café stays in shadow and the recommendation is advisory, not pre-filled as the default.

### 6.5 Fadri usefulness gate — not a paid-offer gate
The model gate is necessary but not enough. The real-data Fadri path is useful only when the
workflow and economics are credible:
1. **Data capture holds:** daily category input completion stays ≥90% on open days during the live Fadri window. Below that, the workflow has an operations problem, not a modelling problem.
2. **Value is positive after uncertainty:** combined cost reduction vs. the café's own baseline has a confidence interval whose lower bound is above zero. If the interval crosses zero, the honest answer is "not proven yet."
3. **The value is operationally worth attention:** estimated savings, avoided sellouts, reduced waste, and owner confidence must justify the daily workflow. There is no pricing hurdle today.
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
- **Traffic forecast** — daily traffic proxied by **drinks sold** (chosen because drinks are usually less supply-constrained than baked goods, but not perfectly clean: peak queues and food-stockout basket abandonment can censor drink sales too; see §12).
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
- **Events (semi-manual at MVP, not fully automatic):** local markets, festivals, marathons, concerts, sporting fixtures, with an impact estimate. Hyperlocal events have no clean global API (assumption-register row 11), so MVP shows the owner a short candidate list to confirm in one tap; auto-feeds are added only where a reliable source exists.

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

- **Auth:** `streamlit-authenticator` — per-user credentials, password **hashes** in `secrets.toml` or Streamlit secrets (never plaintext, never committed), cookie-backed session with expiry. Managed auth is a future upgrade path once we outgrow file-based credentials; possible providers include Supabase Auth, Clerk, Auth.js, or similar.
- **No guest mode for data.** Unlike decant's optional read-only guest, Dial In has nothing useful to show without an account's own history, so unauthenticated users hit the login wall and stop. A logged-out marketing/demo view (synthetic café) is a separate, read-only fixture — never real tenant data.
- **Session → tenant binding, demo path:** in the current Streamlit demo, each credential entry in Streamlit secrets maps directly to one `account_id`. That mapping is server-side configuration, not a browser parameter.
- **Session → tenant binding, database path:** the schema also includes `account_members(auth_subject, account_id)` for a later DB-owned mapping. If that path is used, the lookup must run through a trusted auth/admin path that cannot be influenced by the browser and cannot bypass tenant checks accidentally. Do not keep both mappings active as competing sources of truth.
- **Every data call is account-scoped.** After login, the app uses exactly one server-resolved `account_id`; every read/write is filtered to it and every DB transaction sets the matching RLS account setting.

### 10.8 Tenant isolation & training-data governance *(the part that reconciles the two requirements)*

> **Requirement:** historical data is **not shared between accounts**, **but** the platform may use it to train models. These coexist only if the *serving path* and the *training path* are separated and governed differently.

**Serving path — strict isolation (what a tenant can read):**
- Every query filters on the session's `account_id`. A café reads **only** its own rows. Enforced two ways (defense-in-depth, as decant does with its double-filter):
  1. **Application layer:** a single data-access module injects `WHERE account_id = :session_account_id` on every read/write — no raw table access anywhere else.
  2. **Database layer:** Postgres **Row-Level Security**, keyed to a session-scoped account setting (`app.current_account_id`), so isolation holds even if app code has a bug. No real tenant data is loaded before this is working; the synthetic demo must prove the pattern first on the selected Postgres target.
- **No cross-account reads in the product, ever.** Multi-location benchmarking (§15 Phase 7) compares locations **within the same `account_id`** only.

**Training path — what actually needs cross-account data, and what doesn't.**
We reject blanket "train on everyone's data". The model is split into three layers, governed differently, because the value of pooling is concentrated and decaying while the trust cost is permanent:

Implementation status: this is the target real-data governance design. The current synthetic
demo uses fixed demo weather/event/season rules; it has not trained a shared environment layer.

| Layer | What it estimates | Trains on | Why |
|---|---|---|---|
| **Core demand** (baseline level, attach rate, weekday shape) | the café's *identity* | **that café's own data only** (POS backfill at signup + ongoing) | High trust-sensitivity ("you're helping my rival"); pooling adds little once the café has ~8 weeks of its own history. No cross-account dependency. |
| **Environment response** (weather / event / seasonality elasticities) | generic physics, not identity | **pooled, anonymised, aggregate** across consenting accounts | A single café sees ~2–3 heatwaves and maybe one marathon a year — too few to estimate. The pool sees hundreds. Low trust-sensitivity. **This is the only genuine, lasting network effect.** |
| **Cold-start level prior** (for a brand-new café with *no* POS history) | a starting baseline before the café has data | **pooled, opt-in only**, conditioned on segment/country/footfall band | Needed only for the minority with no backfill (assumption-register row 4); decays to zero as the café's own data arrives. Wide ranges, Low confidence flag. |

- **Default is own-data + the shared environment layer.** Cross-account *level* pooling is **opt-in**, not opt-out — flipped from v2.0 on purpose. Most cafés never need it because their own POS backfill covers cold start.
- **Mechanics:** a **privileged offline training job** (platform admin role, never a user session) fits the environment layer and the cold-start prior. It emits **parameters only** (elasticity coefficients, segment baselines) — never another tenant's raw rows, numbers, or name. A tenant benefits from others **solely as weights in the shared environment layer**.
- **How this is explained to users:** the environment layer is described as *"a benchmark built from cafés like yours,"* not *"we use your sales data."* Honest, and easier to understand.
- **Privacy posture:** training data is **operational counts** (pastries, drinks, weather, events) — no PII, low sensitivity. Residual memorisation risk (a near-unique café in a sparse segment) is bounded by training only on segments with **≥ N consenting accounts**; differential-privacy / k-anonymity is the hardening step for sparse segments — named, not built at MVP. [Likely sufficient given non-PII counts.]
- **Consent:** plain-language clause — *"your sales data is private to your account and is never shown to other accounts. We use anonymised, aggregate patterns to improve the shared weather/event benchmark. You can opt out of contributing and still use the app."* Opt-out of the environment-layer contribution is allowed; opted-out accounts still *consume* the shared layer, they just don't feed it.

**Data-model additions to support this:**
- `accounts` table: `account_id`, `plan`, `contributes_to_shared_layer` (bool, default true), `cold_start_pool_opt_in` (bool, default **false**), `pos_backfill_months` (int — drives the assumption-register row on POS backfill), `created_at`.
- `account_members` table: `auth_subject`, `account_id`, `created_at` for the DB-owned auth-to-tenant mapping path.
- `locations` table: `account_id`, `location_id`, `name`, `timezone`, `city`, `country`, `open_days`, `service_capacity_hint`, `created_at`.
- `data_corrections` table: `account_id`, `location_id`, `date`, `category` nullable, `field_name`, `old_value`, `new_value`, `corrected_by`, `corrected_at`, `reason`.
- `account_id` FK on every operational table (done in §10.1–10.5).
- All cross-account aggregation goes through a separate `shared_layer_features` view readable by the **platform admin role** and by **no tenant role**.

### 10.9 Data operations requirements
These are product requirements, not back-office niceties:

- **Connections:** app code uses `DATABASE_URL`; migration/seed code uses a separate admin connection. The Streamlit app must never run with the schema-owner credentials.
- **Lineage:** every recommendation stores `model_version`, input snapshot, economic config snapshot, weather forecast timestamp, and generation time.
- **Freshness:** after EOD submit, the next-day recommendation should render in the same session. If generation fails, the app shows the last valid recommendation with a clear stale flag.
- **Monitoring:** daily checks track missing input rate, validation rejects, sellout/censoring rate, calibration drift, weather forecast error, and cross-account access test results.
- **Reproducibility:** the model can replay any historical recommendation from stored inputs and config. If it cannot be replayed, it cannot be used in ROI attribution.
- **Access audit:** reads and writes of tenant data are logged with user, account, location, table, and timestamp. This matters more once multi-location accounts arrive.

### 10.10 Operating hours and intraday data *(not required for v1 recommendations)*
The current MVP works at daily grain. That is deliberate. But the product idea must not lose
the intraday path, because sellout time and demand shape are the bridge from "what should I
prep tomorrow?" to "when will we run out?"

Do not fake this in production. Intraday claims require either timestamped POS rows or a clear
synthetic/demo label.

Future schema additions:
- `location_hours`: `account_id`, `location_id`, `weekday`, `opens_at`, `closes_at`, `service_notes`, `effective_from`, `effective_to`. This is separate from `open_days`; a cafe can be open on Saturday with different hours than Tuesday.
- `daily_daypart_metrics`: `account_id`, `location_id`, `date`, `daypart_start`, `daypart_end`, `drinks_sold`, optional category sales. Populated only when POS timestamps exist or in a clearly labelled synthetic demo.
- `sellout_time_estimates`: `account_id`, `location_id`, `date`, `category`, `estimated_sellout_at`, `observed_last_sale_at`, `source`, `confidence`. This separates an observed POS timestamp from a modelled sellout estimate.

Use cases unlocked by these tables:
- "Sweet pastries likely sell out by 12:15 if you prep 44."
- Opening-hours-adjusted demand curves.
- Remaining-hours lost-sales estimates after a sellout.
- Staffing suggestions from traffic shape (roadmap Phase 4).

Guardrail: if timestamped sales are unavailable, the app may show day-level sellout risk
but must not imply an exact sellout time.

---

## 11. Forecasting & Decision Strategy

The forecast produces a **demand distribution**. A separate, explicit **decision layer** turns that distribution into a prep quantity. Keeping them separate is the whole point.

**Cadence & horizon (a build decision, not a detail).** Generation is **event-driven, not a fixed clock**: when the operator submits the end-of-day numbers (§7), the engine runs and the **next day's recommendation is produced instantly** and persisted. The operator can read it from that moment — in the evening (to prep overnight) or the next morning. *Available, not demanded.* It relies on a **next-day weather forecast** (~12–36h horizon) — error propagated into the demand range (§11.4), forecast-vs-actual gap stored (§10.2) and monitored. A refresh re-runs if a materially newer weather forecast arrives before prep.

### 11.1 V1 — Rules-based (MVP)
- **Inputs:** weekday, month, weather forecast, attach rate, trailing same-weekday averages, event flags.
- **Point method (the mean):** expected demand = expected traffic (from drinks) × attach rate, with multiplicative weather/event/season adjustments. In the current synthetic demo these adjustments are fixed demo rules. In the later real-data path they can be replaced by the shared environment layer (§10.8) once that training job exists. Both the traffic model and the attach rate are fit on the café's **own censoring-corrected history** (§12). Attach rate must be computed from *de-censored* pastry demand, **not** raw `sold`; otherwise it is biased downward on exactly the sellout days, silently re-introducing the censoring we removed one level up (see §12).
- **Point → distribution (the part §11.3 needs).** A point forecast has no percentile, and the newsvendor decision needs one. Demand is a small integer count, so we model it as **Negative Binomial** — not Gaussian, and not Poisson (pastry demand is overdispersed; variance > mean). The mean comes from the point method; the dispersion is fit from historical forecast residuals within the same condition bucket (segment × weekday-band × weather-bucket). Where a bucket is thin, fall back to **empirical residual quantiles**. The recommendation is the `q*` quantile of this distribution (§11.3), rounded **up** (a fractional pastry is a whole pastry).
- **Demo vs. Fadri real-data boundary:** the synthetic demo may use the lighter comparable-day de-censoring method described in the companion design doc. The real Fadri path must either use the §12 censoring-aware method or stay in shadow until the lighter method passes the §6.4 ship-gate on Fadri's held-out data. This prevents the demo shortcut from becoming an unexamined real-data shortcut.
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

Important hypothesis, not a fact yet: food stockouts may depress drink sales. A customer who
wanted coffee plus a croissant may walk away if the croissant is gone. If this effect is
material, `drinks_sold` is not fully uncensored on food-sellout days either. The model must
estimate this through `attach_and_balk_rate` and treat it as uncertain until real data or
owner evidence supports it. Do not hard-code an uplift as if every missed pastry also means a
missed drink.

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
3. **Fit with a censoring-aware method.** **Primary: a Tobit (Type-I, right-censored) model on log-demand**, with the sellout flag (§12 step 1) marking the censored observations; a survival/Kaplan-Meier framing is the cross-check on the upper tail. Never ordinary regression on `sold`. [Certain on the framing; Tobit is the committed default, revisited only if it underperforms the cross-check on real data.]
4. **Report the consequence honestly:** estimated lost units and lost margin on sold-out days, as a **range**, feeding the combined-cost metric (§6.2). Never a spuriously precise "you lost exactly 12 sales."

### When the correction is weak — and what we do about it
Censoring-correction is not magic: **it cannot recover a tail it has never observed.** A café that *chronically* sells out has almost no uncensored high-demand days, so the upper quantile (`q*`, §11.3) is **extrapolated, with wide error — exactly on the high-demand days that matter most.** Three responses, in order:
1. **Detect it.** Track each category's **censoring rate** (share of days sold out). Above a threshold (e.g. >40% of comparable days), flag the upper-quantile estimate as low-confidence.
2. **Widen, don't fake.** When the tail is unobserved, the demand range widens and confidence drops (§11.4) rather than emitting a confident extrapolation.
3. **De-censor by design — the principled move.** The recommendation deliberately preps **above** recent sellout levels on a small, controlled share of low-risk days to *observe* where demand actually tops out. This is active experimentation to learn the tail, with the extra-waste cost bounded and disclosed. It is the only way a chronically-under-prepping café ever discovers its true ceiling, and it is the difference between a tool that breaks the under-prep loop and one that merely re-fits it.

### A caveat on the traffic proxy
"Drinks are uncensored" holds on ordinary days but can break in two ways. First, a single
barista, a long queue, and walk-outs mean drink sales are **throughput-censored** on the
busiest days. Second, food stockouts may reduce drink purchases if some customers came for a
coffee-plus-food basket and abandon the whole order when food is gone. We therefore (a) treat
very-high-traffic days as potentially censored on the drinks side too, (b) mark food-sellout
days as possibly depressing drinks when `attach_and_balk_rate` is non-zero, and (c) lean on
external footfall signals (weather, events, day-of-week) rather than drinks alone when traffic
approaches the café's observed service ceiling or food sold out early. [Likely material for
high-volume cafés and brunch-heavy cafés.]

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
The instinct is "a new café has zero rows, so it must borrow from other cafés." Mostly false. **Most cafés arrive with 1–2 years of their own POS history** (Square/Toast/Lightspeed retain it). We backfill it at signup, so the median new café trains its **own** core model from day one — no other account's data required. Cold start is a minority problem, not the default. [Likely — gated on POS export coverage, assumption-register row 4.]

What actually drives the recommendation, by situation:

| Situation | Core demand (level/attach) | Environment response (weather/event) | Confidence |
|---|---|---|---|
| **Has POS backfill** (the common case) | café's **own** backfilled history | shared environment layer (§10.8) | Medium→High from day 1 |
| **No backfill, 0–8 weeks** | **opt-in** cold-start prior (segment/country/footfall band) + 3-question setup, shrinking toward own data as it arrives | shared environment layer | Low; ranges wide |
| **8+ weeks, any café** | café-specific dominates | shared environment layer (still pooled — café never sees enough rare events alone) | High |

Two things never change regardless of history: (1) the **environment-response layer is always shared** — a café with three months of data still can't estimate its own heatwave or marathon elasticity, so the pool carries it permanently; (2) the **core baseline stays café-private**.

This is why `account_id`/`location_id` are mandatory (§10). The cross-café benefit flows **only through shared parameters** (§10.8) — a new café inherits an *elasticity* or an opt-in *prior*, never another café's actual rows. Tenant isolation and pooling aren't in conflict; they live on opposite sides of the serving/training split, and the only data that crosses the boundary is the low-sensitivity environment layer.

---

## 14. Measurement & Attribution Design *(how we learn if it works)*

A decision tool that cannot evaluate its own recommendations teaches the wrong lesson. The
goal is not to build a sales proof today. The goal is to learn whether the model would have
improved prep decisions under honest uncertainty.

1. **Baseline period (2–4 weeks):** run in shadow mode — generate recommendations, log them, but the owner preps as usual. Establishes the café's own pre-Dial-In waste, sellout frequency, and combined cost. *Note the friction trade-off:* in shadow there is no acted-on recommendation to pre-fill the EOD input (§7), so `prepared` must be entered manually and completion will dip during exactly the period we need clean baseline data. Mitigate by pre-filling the shadow input with the café's own trailing same-weekday prep and keeping the baseline short.
2. **Naive baseline benchmark:** the model must beat last-week-same-weekday and trailing-4-week-same-weekday on pinball loss before it is allowed to influence decisions (§6.1).
3. **Real-data comparison — stated honestly.** For Fadri, the primary readout is within-café: recommendation vs actual prep, observed outcome, and modelled cost. Cross-café rollout design is optional future context, not the current plan.
4. **Adherence-conditioned readout:** because `recommendations.adhered` is logged, we can compare outcomes on days the owner followed the recommendation vs. days they overrode it — the cleanest within-café causal signal we can get without a formal experiment.
5. **Headline impact metric:** change in **total expected cost of mis-prep per week** (waste COGS + estimated lost margin), reported with a confidence range, never as a bare percentage.

### 14.1 Fadri measurement protocol
Before using real Fadri data for decisions, write down:
- **Baseline window and live window.** Default is 2–4 weeks shadow plus at least 4 weeks live, extended if closures/events leave too few usable open days. This is not a formal power guarantee, and it is not enough by itself to prove calibration. It is the minimum learning window before deciding whether the pilot should continue.
- **Owner-configured tolerance:** the owner chooses the waste/run-out preference through the economics setup (§10.5, §11.3). We do not call a recommendation "better" if it violates that preference.
- **Attribution view:** report three numbers together — observed waste proxy, sellout frequency, and combined expected cost. Reporting only the best-looking one is cherry-picking.
- **Decision log:** every override gets an optional reason (`weather felt wrong`, `supplier issue`, `large order`, `owner judgement`, `other`). Overrides are signal, not failure; they tell us what the model missed.

---

## 15. Future Roadmap
This roadmap is intentionally broader than the first build. Some items are not Phase 1, 2, or
3, but they are noted now so we can assess the product honestly instead of narrowing the idea
too early.

- **Phase 1A — Decision demo completeness:** show the weather forecast, event list, season label, confidence reason, and top drivers directly in the recommendation UI. The engine already needs these inputs; hiding them makes the advice feel arbitrary.
- **Phase 1B — Attribution basics:** populate `prepared`, `adhered`, and `override_delta` on recommendation rows after closeout; add override reason capture; show adherence-conditioned results separately from general scorecard claims.
- **Phase 1C — Economics setup:** add category economics confirmation and a "waste vs run-out" control backed by `Cu`, `Co`, salvage share, attached-drink margin, and attach-and-balk defaults. Until economics are confirmed, recommendations should be labelled as using defaults.
- **Phase 1D — Data-quality workflows:** support closed days, late corrections, bad-input repair, menu-version changes, and correction audit history in the UI. Without this, the model will learn from dirty operational data.
- **Phase 1E — Honest measurement:** add naive baselines, pinball loss, calibration, bias, censoring rate, combined expected cost, and synthetic-vs-real labels. Revenue or savings must be shown as an estimate with assumptions, not as "generated revenue."
- **Phase 1F — Weather/event/season layer:** real weather API, forecast-vs-actual storage, semi-manual event confirmation, public/school holiday handling, bridge days, tourism season, and low/mid/high season labels. Automatic hyperlocal events remain a risk until source coverage is proven.
- **Phase 2 — Intraday:** opening hours, hourly/daypart demand curves, sellout-time prediction, remaining-hours lost-sales estimates, and service-capacity/queue-balking detection. Gated on timestamped POS data; synthetic-only display is allowed for demos if labelled.
- **Phase 3 — POS backfill and import:** CSV import first, then POS APIs. Sold figures become imported; `prepared` remains manual. Timestamp coverage is measured before enabling intraday claims.
- **Phase 4 — Staffing:** convert traffic forecasts and demand curves into shift suggestions. This must stay secondary to prep until there is enough timestamped traffic data.
- **Phase 5 — Ingredients:** explode category or SKU prep into raw inputs through recipe mappings.
- **Phase 6 — Inventory optimisation:** ordering and par levels. This is adjacent, not the wedge.
- **Phase 7 — Multi-location benchmarking:** compare locations only within the same account; cross-account benefit stays in shared parameters, never raw rows.
- **Phase 8 — SKU-level prep:** move from sweet/savory categories to individual products. Category-level is an MVP simplification; many real operators will eventually ask "which pastry?", not just "how many sweet?"
- **Long-range — Shared environment model:** pooled weather/event/season elasticities with consent, minimum segment sizes, sparse-segment privacy checks, and opt-out monitoring.

---

## 16. Edge Cases & Regime Changes
- **Closures / holidays:** `is_open = false`; excluded from the series.
- **Menu changes:** new/removed product → `menu_version` bump; pre-change history down-weighted for affected categories.
- **Hours changes / ownership changes:** treated as regime breaks — pre-break history down-weighted and ranges widened; if the break invalidates most history, fall back to the cold-start path (§13: own remaining data + shared environment layer, opt-in prior only if truly no usable history).
- **Bad manual input:** caught by the `sold ≤ prepared` rule (§10.6); flagged for one-tap correction.
- **POS outage / missing import:** fall back to traffic priors; mark confidence Low.

---

## 17. Value Sizing *(not a pricing plan today)*

This section is kept as a modelling discipline, not because Dial In is currently planned as a
paid product. If the expected value is tiny, the recommendation may still be an interesting
forecasting exercise, but it will not matter operationally. The framework helps decide whether
the problem is worth attention for Fadri-style cafés.

**Size the addressable pool first, then apply a single forecast-driven reduction — do not add two independent savings (that would double-count the tradeoff in §6.2).**

Baseline monthly **cost of mis-prep** for an example single-location café (preps ~80 pastries/day):

| Component of mis-prep cost | Baseline (illustrative) |
|---|---|
| Waste: ~12 units/day discarded @ €0.90 COGS × 30 | ~€324 |
| Lost margin: ~8 sellout days × ~10 unmet units @ €2.60 | ~€208 |
| **Total addressable mis-prep cost** | **~€532/mo** |

A better forecast shrinks the **whole** waste↔stockout curve inward; the newsvendor quantile (§11.3) only chooses *where on the curve* the café sits (more waste vs more stockout), it doesn't reduce the total — **accuracy does.** A credible combined reduction of **20–30%** on the €532 pool → **~€105–160/mo** saved. AOV uplift (the attached coffee on a recovered pastry sale) is real upside, deliberately left unsized.

The 20–30% reduction is an assumption to test against real or synthetic replay, not a promise.
If this ever becomes a commercial product, pricing can be revisited then. Today the useful
question is simpler: does the model reduce expected mis-prep cost enough to be worth using?

### 17.1 Value validation checklist
The current value logic is a framework, not evidence. Before treating any savings estimate as
credible, collect:
- Actual daily prep, sold, and leftover handling by category.
- Retail price, unit COGS, salvage behaviour, and attached-drink margin.
- Number of open days, sellout days, and owner-estimated missed demand.
- Whether the owner values saved attention, staff stress reduction, and better customer experience enough for them to matter; if not, leave them out of the estimate.
- Whether baked goods are central enough to the shop that food sellouts change the day, not just the snack display.

---

## 18. UX Requirements
- **Mobile first.** Owners use a phone, often one-handed, mid-service.
- **Fast.** Page load < 3s; the recommendation is the first thing rendered.
- **Simple.** No dashboard or report on the landing screen; no analytics jargon. The "why" is one tap deep, not in the owner's face.
- **Honest UI.** Confidence and range are always shown — a single number with no range is forbidden, because it implies certainty the model doesn't have.

---

## 19. Non-Goals
Dial In is explicitly **not**: an inventory system · an accounting system · a POS replacement · a workforce-management platform · a BI / general reporting tool · a recipe manager.

It does **one** job: help a mixed-focus specialty coffee place decide how much fresh food to
prep, then learn honestly whether that advice was better than the baseline.

---

## 20. Open Questions & Assumptions Register
| # | Assumption / open question | Risk if wrong | How we'll close it |
|---|---|---|---|
| 1 | Drinks sold is a reliable, near-uncensored traffic proxy | Whole traffic→demand chain weakens | Validate attach-rate stability on pilot data before trusting it |
| 2 | Owners will enter `prepared` daily | Censoring logic degrades | Pre-fill + one-tap confirm; monitor completion; degrade gracefully |
| 3 | Per-café `Cu`/`Co` can be captured at onboarding | Wrong service level → systematic mis-prep | Sane category defaults; let owners tune by feel ("waste vs run-out" slider) |
| 4 | **Most signups have exportable POS backfill (1–2 yrs)** — the assumption that kills most cold start | If <~70% have backfill, cross-account cold-start pooling matters far more than §13 claims | Measure `pos_backfill_months` on first cohort; if low, reconsider opt-in default on the cold-start prior |
| 5 | Shared environment layer beats per-café weather/event estimation | If café-level rare-event signal is good enough alone, the only lasting network effect disappears | Compare pooled-elasticity vs café-only on held-out rare-condition days |
| 6 | The single-location use case is operationally valuable enough to justify attention | The model may be interesting but not useful in practice | Validate §17 with Fadri-style economics before spending time on broader use |
| 7 | GUC-based RLS works cleanly with `streamlit-authenticator` on the selected Postgres target | If not, tenant isolation design needs rework before real data | Prove with synthetic demo on local Postgres and Neon: app role, `SET LOCAL app.current_account_id`, and cross-account query tests |
| 8 | Customers accept the shared environment layer when framed as a benchmark | Trust pushback; contribution opt-outs shrink the pool | Plain-language clause + `contributes_to_shared_layer` opt-out (still consume, don't feed); monitor opt-out rate |
| 9 | Shared layer won't memorise sparse segments | Indirect leakage of a near-unique café | Train shared layer only on segments with ≥ N consenting accounts; DP/k-anonymity for sparse segments |
| 10 | POS timestamps available often enough for intraday | Phase 2 (hourly) blocked | Check timestamp coverage in Fadri data and any later real datasets |
| 11 | Hyperlocal events can be sourced as an "automatic" feed | §9 oversells; no clean global API for a town-square market | Treat events as semi-manual at MVP (owner confirms a short list); auto-feed only where a reliable source exists; size coverage before promising |
| 12 | Chronic-sellout cafés will tolerate the de-censoring probe (occasional deliberate over-prep) | The tail-learning mechanism (§12) is rejected by waste-averse owners | Make probe opt-in, bounded, and framed as "we'll occasionally test a bit higher to find your real ceiling"; cap added waste |
| 13 | Fadri's real operating bands are close enough to seed a credible synthetic demo | Fake-looking data will hurt trust before the product is discussed | Get rough drinks/day, attach, waste, and sellout ranges; if unavailable, label Fadri as fictionalised and do not imply realism |
| 14 | Category-level recommendations are enough for MVP | Owners may ask "which pastry?", not just "how many sweet?" | Track override reasons and sales mix; promote SKU-level prep only if category advice is too blunt |
| 15 | The simplified demo de-censoring method is close enough to show behaviour | Demo teaches the wrong model habit | Keep it synthetic-only; the real Fadri path must pass §6.4 before trusted recommendations |
| 16 | The owner can supply or approve economics inputs | `q*` becomes a fake precision number | Store defaults separately from confirmed values; show confidence lower until confirmed |
| 17 | Weather APIs are available, cheap, and reliable enough for daily use | Missing or stale forecasts make recommendations look random | Store forecast timestamp, fallback to seasonal normal, monitor weather error, and show Low confidence when stale |
| 18 | Local event data can be kept current without annoying owners | Event effects become stale or wrong; false event lifts hurt trust | Start with owner confirmation for a short candidate list; only automate sources with proven local coverage |
| 19 | Low/mid/high season labels are understandable and useful | Season labels can become hand-wavy narrative rather than model signal | Tie labels to configured calendar/tourism periods and show their measured historical lift |
| 20 | Opening hours are stable enough to model intraday demand | Hours changes create false demand curves and false sellout-time claims | Version `location_hours`; treat hour changes as regime breaks |
| 21 | Synthetic demand curves help demos without misleading users | Demo may imply precision that production lacks before POS timestamps | Label synthetic curves clearly and disable real intraday claims without timestamped POS data |
| 22 | Estimated revenue/savings can be explained without overclaiming | Users may read modelled lost sales as proven money | Report observed waste proxy, sellout frequency, and combined expected cost with assumptions and uncertainty |
| 23 | Recommendation hashes are enough for replay | Hashes prove identity but not replayability if raw snapshots are missing | Store full input/config snapshots or reconstructable snapshot tables before claiming audit-grade replay |
| 24 | Override reasons will be entered honestly | Owners may skip reasons or use "other", weakening attribution | Keep reason capture optional but one tap; treat missing reasons as a signal about UX friction |
| 25 | Food stockouts reduce drink sales through basket abandonment | If true, drinks are not a clean traffic proxy on sold-out days; if false, we overstate stockout cost | Estimate `attach_and_balk_rate` conservatively, compare drink sales on similar food-sellout vs non-sellout days, and treat the effect as uncertain until validated |
| 26 | The target shop treats baked goods as a meaningful part of the offer, not a minor add-on | If food is incidental, the product may solve a small annoyance rather than a paid problem | Qualify early users by food revenue share, weekend sellout frequency, sellout time, waste pain, and whether food stockouts affect basket size or repeat visits |
| 27 | Customer counts are not required in the first version | Without explicit footfall, drinks remain the traffic proxy and may miss non-buyers or walkaways | Add customer counts, door counts, or order counts later only if drinks and POS history are insufficient for model gates |

---

## 21. Build Readiness Gates
This is the checklist that moves the project from an interesting idea to something worth
testing with synthetic data and, later, Fadri's real data:

1. **Schema gate:** account/location/category grain implemented; RLS test passes; `recommendations` stores lineage and economics snapshots.
2. **Data gate:** validation rejects bad counts; missing inputs are imputed but excluded from censoring training; corrections are audited.
3. **Model gate:** rules model beats both naive baselines on pinball loss, is calibrated, and shows no systematic bias (§6.4).
4. **Usefulness gate:** Fadri-style economics and operational value are large enough to justify attention, with uncertainty shown (§6.5, §17.1).
5. **Honesty gate:** all claims separate observed facts, modelled estimates, and synthetic/demo behaviour.

Failing any gate does not kill the project. It tells us what problem we actually have: data capture, model quality, tenant safety, or operational value.

---

## 22. Positioning
Dial In helps a mixed-focus specialty coffee place decide what to prepare tomorrow — combining
the owner's instinct with a model that respects how the decision actually works: running out
costs more than throwing out, and you can't manage demand you never observed.

**"What should we prepare tomorrow?"** Everything else is secondary.
