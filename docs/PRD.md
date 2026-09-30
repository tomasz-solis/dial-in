# Dial In: product requirements (PRD)

Version 1.3. Author: Tomasz Solis. Status: draft. Created 2026-05-31, last updated 2026-06-01.

Companion: `2026-05-31-synthetic-data-and-demo-design.md` (demo and generator design; v1 input and cadence are reconciled here). Project type: learning project, decision-support web app, demo built for Fadri. Current target: a synthetic demo account first, then a Fadri Café real-data account once data exists.

> Short version. Dial In is a fresh-prep decision tool, ready for a tightly managed, advisory paid pilot but not for broad self-serve SaaS sales. It answers one question for a mixed-focus specialty coffee place: how much fresh vegan sweet and savory food should we prep tomorrow? Sales are censored when food sells out, and running out doesn't cost the same as waste. Dial In treats prep as a newsvendor decision: forecast the demand distribution, then pick the prep quantity that minimises expected cost given the café's margins and waste. The login-gated synthetic account shows the workflow; proof worth selling must come from frozen recommendations and held-out outcomes in a controlled real-data pilot.

## 1. Summary

Dial In started as a hands-on learning project and a practical demo for a real specialty coffee context. The current status (see the short version above and §23) is a managed advisory pilot, not self-serve SaaS.

Learning goals:

- Docker and local Postgres development.
- Demand modelling on synthetic and, later, real café data.
- Censored demand, uncertainty and calibration.
- Turning forecasts into decisions, not dashboards.
- Better confidence and accuracy, step by step, without overclaiming.

The finished app has two kinds of account:

| Account | Data |
|---|---|
| Demo | Generated synthetic data with weather, events, seasonality, sellouts, waste and a clean observed/truth split |
| Fadri Café | The same app and decision flow, on real Fadri data once available |

### 1.1 Before production: non-real forecast inputs

Before Dial In runs a real café's day, every non-real input that can affect a recommendation must be replaced with a real source, confirmed by the owner, or clearly labelled demo or advisory. This is a product requirement, not just documentation.

| Input | State |
|---|---|
| Weather | Done: forecasts are real. `OpenMeteoWeatherProvider` pulls live forecasts and ERA5 historical reanalysis proxies from Open-Meteo. `scripts/fetch_weather.py` writes them to the `weather` table with `forecast_made_at` (scheduled before the daily refresh), and the engine detects stale forecasts and falls back to seasonal normal with lower confidence. The generator still seeds historical demo weather, because the synthetic sales came from it; only forward forecasts are observed feed data. Recent weather outcomes are reanalysis proxies, not station readings. Still to do: re-fetch when a materially newer forecast arrives (§11), and richer condition mapping. |
| Usage and adherence | Demo closeouts, adherence, overrides and health rates are synthetic until real operators use the app. They can't serve as adoption, adherence or ROI evidence. |
| POS sales and traffic | Generated drink and category sales stand in for POS import or owner-entered closeouts. Production must audit rejects, re-imports, missing days and corrections before rows feed recommendations. |
| Events, holidays, tourism season | Generated events and configured seasonal lifts must become confirmed calendars, owner-approved local events or clearly marked assumptions. Unconfirmed events should lower confidence, not quietly lift demand. |
| Economics | Prices, COGS, salvage, attached-drink margin and stockout-cost assumptions are defaults until the owner confirms them. Recommendations on defaults stay advisory and lower confidence. |
| Opening hours, closed days, menu versions | Demo defaults must become real hours, closure review and menu or regime-break markers so comparable history stays clean. |
| Replay, savings, scorecards | Synthetic replay isn't proof of business impact. Real value claims need held-out real data, a baseline comparison, calibration checks and the §6.4 model gates. |

Independent cafés decide food prep by gut. The decision is daily, irreversible (fresh food can't be un-baked) and asymmetric (running out costs more than throwing out). Owners get it wrong both ways and rarely have time to work out why.

Dial In recommends a daily prep quantity per product category, with a demand range and the reasons. The operator closes out the day, and the next day's recommendation appears at once, readable that evening or the next morning. It uses sales history, weather and event forecasts, and seasonality. In v1 the numbers are entered by hand (about 30 to 60 seconds); once POS integration lands, `sold` is imported and daily effort drops toward the target of one input in under 30 seconds.

Three things separate Dial In from a forecast in an app:

1. It optimises a decision, not an accuracy score. The output is the prep quantity that minimises expected money lost, trading waste cost against stockout cost, not the most likely sales number.
2. It corrects for censored demand. It tells "sold 40 because demand was 40" apart from "sold 40 because we only made 40", and learns from both correctly.
3. It is measurable. Every recommendation, the operator's actual decision and the outcome are logged, so impact is attributed, not asserted.

## 2. Problem

Independent cafés decide daily prep by intuition, and intuition breaks under variance: weather, tourism, local events, seasonality and weekday vs weekend each move demand by amounts nobody can hold in their head at once.

The first target is narrower than "any coffee shop": a specialty coffee place where fresh vegan sweet and savory goods are a real part of the offer, often baked by the operator, and where weekend demand regularly beats prep. A concrete scenario: open 09:00 to 13:00, food sold out by about 11:30, then 1.5 hours of coffee-only service. That's a missed basket and a worse customer experience, weighed against the real cost of over-baking, not just an accuracy problem.

Every day ends in one of two errors.

Under-preparation (stockout): items sell out before demand ends. It costs margin on every unmet sale, lower order value (no pastry with the coffee), disappointed regulars and staff stress. It is also invisible in the data: when you sell out, sales stop at what you baked, and you never see how much more you could have sold. That's the core measurement problem (§12).

Over-preparation (waste): surplus is binned, discounted or eaten by staff. It costs COGS, margin and labour, and for many owners it genuinely hurts.

The two aren't symmetric. A stockout usually costs 2 to 4x more per unit than waste: a missed croissant loses the full retail margin (about €2.60 on a €3.50 item), an unsold one only its COGS (about €0.90). [Likely; the exact ratio is café-specific and configured per customer.] A tool that minimises both errors equally solves the wrong problem. Dial In encodes the asymmetry (§6, §11).

## 3. Vision

A small, usable decision-support app for fresh-food prep. The first version proves the workflow on synthetic data; the Fadri version runs the same workflow on real data.

When the operator closes out the day, the next day's recommendation appears (readable that evening to prep overnight, or the next morning) and reads as quickly as a weather forecast:

- Expected traffic: 190 to 220 drinks.
- Recommended prep: sweet pastries 54 (demand range 46 to 61, prep at about the 78th percentile per §11.3); savory pastries 31 (demand range 25 to 36).
- Risk flag: high demand likely, sunny Saturday plus local market.
- Confidence: high (similar to 18 comparable past days).

The operator takes it in within 30 seconds and gets on with the day.

## 4. Principles

1. Low friction beats marginal accuracy. A good-enough model used daily beats a great one that needs babysitting. Owner effort budget: under 30 seconds a day and under 15 minutes of onboarding, as a post-POS target. In v1, before POS, input is manual (drinks, sweet and savory sold, sweet and savory prepared, about 30 to 60 seconds); the budget tightens once POS supplies `sold` (§9).
2. Every manual input must justify itself and be protected. `prepared` can never be automated: it's the only way to detect a stockout. In v1 the operator also enters `sold` until POS integration lands. The model leans on these, so they are validated, not just requested (§10.6).
3. Recommend, don't report. The default screen is a decision, not a dashboard. Analytics exist, never on the landing screen.
4. Optimise expected money, not forecast error. Accuracy is the means; the end is the prep quantity that loses the least money given this café's economics.
5. Be honest about uncertainty. When the model is guessing (new café, volatile weather, unusual event), it says so and widens the range instead of faking a confident number.

### 4.1 Deployment and database

Dial In is Postgres-first and provider-neutral. The requirement is a relational Postgres database with tenant isolation, recommendation and outcome logging, and a clean synthetic observed/truth split, not a particular vendor.

| Target | Role | Notes |
|---|---|---|
| Local Docker Postgres 17 | Default development database | Schema work, migrations, generator development, tests and local replay. |
| Neon free Postgres | Hosted Streamlit demo database | Needed on Streamlit Community Cloud, which can't reach a laptop database. Demo and Fadri path only for now. |
| Supabase Postgres | Compatible future target | Fine if Supabase features are ever needed, but the app must not depend on Supabase client APIs or Supabase Auth. |
| Paid managed Postgres | Optional future production option | Not needed for learning or the demo; reconsider only if real usage outgrows free or local infrastructure. |

The app reads its connection from `DATABASE_URL`: Docker Postgres locally, Neon with `sslmode=require` in Streamlit secrets for the live demo. Migrations and seeding use a separate owner/admin connection, never the low-privilege app connection.

Neon is the hosted demo provider, not the architecture. Neon Auth stays off; `streamlit-authenticator` stays the login pattern until there's a concrete reason for managed auth.

Docker is part of the development plan, not a prerequisite for the first hosted demo. It comes in a later pass as a small local Postgres practice path: `docker-compose.yml`, `.env.example`, migrations and a simple migration command that runs through the container.

## 5. Target user and fit

### Current fit

Mixed-focus specialty coffee places that bake meaningful sweet and savory goods:

- One location, 2 to 10 staff, owner-operated, significant fresh-food prep.
- Best early fit: places where weekend sellouts are common.
- Weaker fit: coffee-first shops where cookies or packaged snacks are a nice extra and food sellouts don't change revenue, customer experience or owner stress.
- Has a POS (Square, Toast, Lightspeed, Shopify) or can export CSV.
- No data team, analyst or inventory manager. Limited technical patience.
- Current real-world target: friends in a Fadri-style specialty coffee context, where vegan sweet and salty goods are baked in house and sellout timing is a real pain.

### Future fit

Small multi-location operators (2 to 10 sites), planning centrally and wanting per-location recommendations. They matter beyond their size: higher willingness to pay (value scales with sites, one decision maker) and pooling within one account, so a new site inherits its siblings' patterns at once without any cross-account sharing (§13).

> The fit filter matters even without a sales plan, because a learning project can drift into solving a fake problem. If food is incidental, Dial In may be technically interesting but operationally unimportant.

### Alternatives it has to beat

| Alternative | Why it exists | Why Dial In can win |
|---|---|---|
| Owner intuition, handwritten par sheets | Free, trusted, fast | Breaks under weather and events, and can't learn from censored sellouts |
| POS reports, spreadsheets | Real sales history | Report sales, not unmet demand, and leave the prep decision to the owner |
| Generic inventory tools | Broader operations coverage | Usually optimise stock or accounting, not daily fresh prep under asymmetric cost |
| Enterprise demand planning | Strong modelling | Too heavy and expensive for an independent café or small group |

The target is narrow on purpose: fresh-prep decisions for small operators where sellouts censor demand and fresh food matters. For accounting, purchasing, generic dashboards, or coffee with incidental snacks, Dial In is the wrong tool. A commercial go-to-market plan is optional future context, not the current goal.

## 6. Learning, model and usefulness metrics

Three separate things: the metric the model is optimised on, the outcomes we estimate, and the usage signals that show the workflow works. Mixing them is how prep tools fool themselves. Here they are learning gates and usefulness checks, not sales promises.

### 6.1 Primary technical metric

- Pinball (quantile) loss on held-out days, at the café's operating quantile (configured per café; about 0.78 in the §11.3 example).
- Calibration: on days flagged high confidence, realised demand falls inside the stated range at least at the stated rate (an 80% range contains demand about 80% of the time).
- The floor: beat both naive baselines, last week's same weekday and the trailing 4-week same-weekday average. If Dial In can't beat both on pinball loss, it ships nothing.

### 6.2 Operational outcomes we estimate

These follow from accuracy plus the chosen service level; they aren't independent dials. They trade off along one curve, and only a tighter forecast improves both.

- Waste reduction: `prepared − sold` is an upper bound on waste, not waste itself, because unsold units may be discounted, carried over (multi-day shelf life) or eaten by staff. True waste = `(prepared − sold) × (1 − salvage_share)`, measured on non-sellout days against the café's own pre-Dial-In baseline. For single-day items (croissants) `salvage_share ≈ 0` and the two match; for cookies they don't. `salvage_share` is the same per-category parameter that feeds `Co` in §11.3.
- Stockout reduction: measured as sellout frequency (`sold_out` days, §12 step 1) against baseline. The size of lost sales is a modelled estimate (censored, §12), reported as a range, never a hard number.
- Combined cost, the honest headline: total expected money lost per week (waste COGS plus estimated lost margin). One number that falls when either error shrinks.

> We don't claim "cut waste 15% and stockouts 20%" as independent guarantees; with a fixed forecast they trade off. The honest target: estimate the total expected cost of mis-prep, explain the waste vs stockout tradeoff, and learn whether the recommendations would have improved decisions. Any savings number is an estimate with assumptions, not a promise.

### 6.3 Workflow metrics

- Weekly active use on more than 80% of open days.
- Daily input completion above 90%.
- Median daily interaction under 30 seconds; onboarding under 15 minutes.
- Recommendation adherence (the `adhered` flag, §10.4: `prepared` within ±max(2, 10%) of the recommended prep), which also signals trust early.

### 6.4 Model ship gate (when a café's model may drive prep)

A café's model moves from shadow (§14) to live only when all of these hold on that café's held-out days. They are full ship gates, not claims a four-week pilot can prove everything:

1. Enough evidence first: enough held-out open days to evaluate the category honestly. In a short Fadri window these checks are diagnostics, not hard pass/fail until the sample is big enough to mean something.
2. Beats both naive baselines on pinball loss at the operating quantile, by a margin outside noise when the sample supports that test.
3. Calibrated: the p10 to p90 range contains realised demand about 75 to 85% of the time once there are enough held-out days. Before that, calibration is directional evidence with wide uncertainty, not a pass badge.
4. No systematic bias: mean signed error over the latest usable window shows no chronic under-prep (§12). The ±5% target is for mature data; a tiny pilot can't estimate it tightly.
5. Censoring rate observed: if a category sells out on more than 40% of comparable days, its upper quantile is flagged low confidence and the de-censoring probe (§12) is active before the model is trusted on high-demand days.

Until the gates are met with enough data, the café stays in shadow and the recommendation is advisory, not pre-filled as the default.

### 6.5 Fadri usefulness gate (not a paid-offer gate)

The model gate is necessary but not enough. The real Fadri path is useful only when the workflow and economics hold up:

1. Data capture holds: daily category input completion stays at 90% or more on open days in the live window. Below that it's an operations problem, not a modelling one.
2. Value is positive after uncertainty: the confidence interval on combined cost reduction vs the café's own baseline has a lower bound above zero. If it crosses zero, the honest answer is "not proven yet".
3. The value is worth the attention: estimated savings, avoided sellouts, less waste and owner confidence justify the daily workflow. There's no pricing bar today.
4. No hidden service-level trade: stockout frequency can't rise past the café's configured tolerance while waste falls. A cheaper-looking result that quietly accepts too many stockouts is a bad recommendation.

## 7. Core user journey

One event-driven action: close out the day, and the next day's recommendation appears at once, readable from then on (evening to prep overnight, or next morning).

End of day, the single action:

- v1 (before POS): type 5 numbers, `drinks_sold`, `sweet_sold`, `savory_sold`, `sweet_prepared`, `savory_prepared` (about 30 to 60 seconds).
- After POS: POS supplies the `sold` figures, and the operator only confirms `prepared` (pre-filled with the recommendation, one tap, about 10 seconds).
- On submit, the engine runs and tomorrow's recommendation appears at once and is saved: range, risk flag, one-line reason, and an optional "why" with 3 drivers.

Any time after (read-only, about 15 seconds): reopen Dial In to see the saved recommendation. No recompute.

Effort: about 30 to 60 seconds a day in v1, under 30 seconds after POS. If the owner skips a day, §10.6 degrades gracefully instead of breaking.

## 8. MVP scope

The MVP is the rules-based version (V1, §11.1) inside the full decision and measurement machinery. Decision framing and data discipline ship first; model sophistication comes later.

In scope:

- Daily recommendation engine per category (sweet, savory): recommended prep, demand range, confidence, top 3 drivers.
- Traffic forecast, with drinks sold as the proxy. Drinks are usually less supply-constrained than baked goods, but not perfectly clean: peak queues and food-stockout basket abandonment can censor drink sales too (§12).
- Demand forecast: sweet and savory demand from traffic × attach rate, adjusted for weather, weekday, season and events.
- Censored-demand correction (§12), in the MVP because without it the model trains on its own past mistakes.
- Newsvendor service-level policy: turn the demand distribution into a prep quantity using the café's cost ratio (§11.3).
- Risk flag: days where the recommended prep sits well below the upper demand band.
- Recommendation and outcome logging: every recommendation, the actual prep and realised sales, saved for attribution (§14).

Out of the MVP: ML models (V2), hourly or intraday forecasting, ingredients and staffing, a multi-location benchmarking UI (roadmap §15).

## 9. Data collection

Collection should be nearly invisible; the owner should never feel they're maintaining software. The end state is one pre-filled manual number a day, with everything else automated or imported. v1 starts manual and reduces effort as integrations land.

Required daily input in v1 (manual): drinks sold, sweet sold, savory sold, sweet prepared, savory prepared (about 30 to 60 seconds). `prepared` stays manual for good (it's the operator's decision); the `sold` figures are manual only until POS integration.

Imported from POS (a later enhancement, not an MVP assumption):

- Drinks, sweet and savory sold (daily counts), which takes them out of manual entry.
- Time of the last sale per category, if the POS exposes timestamps, to detect when a stockout happened. If it doesn't, all intraday claims are disabled, not faked (§12).

Automatic external feeds:

- Weather, forecast and actual: temperature, rain, wind, condition. Both the forecast we acted on and what actually happened are stored, because forecast error is itself a feature and a source of recommendation error (§11.4).
- Calendar: weekday, month, public and school holidays, bridge days.
- Seasonality: month, quarter, tourism season.
- Events (semi-manual at MVP): local markets, festivals, marathons, concerts and sports fixtures, with an estimated impact. Hyperlocal events have no clean global API (assumption register row 11), so the MVP shows the owner a short candidate list to confirm in one tap, and automates only where a reliable source exists.

## 10. Data model

> Every table carries `account_id` (the login and tenant, the isolation boundary) and `location_id` (a site under an account; a multi-location operator has several). A single-location café is the n=1 case. This is non-negotiable for two reasons: `account_id` enforces that no café ever sees another's data (§10.7, §10.8), and it lets a multi-location operator pool within its own account and the platform learn a shared weather and event benchmark across accounts, through model parameters only, never raw rows (§10.8, §13).

### 10.1 Operational demand tables

The UI starts with two categories (`sweet`, `savory`), but storage is account × location × date × category. Hardcoded `sweet_*` and `savory_*` columns would make SKU-level prep (§15) a migration instead of a config change.

`daily_metrics`, one row per location-day:

| Column | Notes |
|---|---|
| `account_id` | Tenant and login, the isolation boundary |
| `location_id` | Site key, under `account_id` |
| `date` | Local business date, not UTC calendar date |
| `timezone` | For closeout, forecast horizon and timestamped POS data |
| `is_open` | Closure flag. Closed days are excluded from training, not treated as zero demand. |
| `drinks_sold` | Traffic proxy, treated as nearly uncensored except at observed throughput limits (§12) |
| `input_source` | `confirmed`, `corrected` or `imputed` (§10.6) |
| `menu_version` | Current menu or config version, for regime breaks |
| `recorded_at` | When the closeout was entered or imported |

`daily_category_metrics`, one row per location-day-category:

| Column | Notes |
|---|---|
| `account_id`, `location_id`, `date` | Join to `daily_metrics` |
| `category` | MVP values `sweet` and `savory`; later SKUs use the same grain |
| `sold` | Observed units sold, censored by `prepared` |
| `prepared` | Manual input, the censoring threshold |
| `sold_out` | Derived: did the category hit its prepared cap? |
| `stockout_detected_by` | `inferred_cap`, `pos_out_of_stock`, `manual` or `unknown` |
| `time_last_sale` | Nullable, only if the POS gives timestamps |
| `salvage_share_observed` | Nullable daily override when leftovers were discounted, carried over or eaten by staff |
| `input_source` | `confirmed`, `corrected` or `imputed` |

Primary keys: `daily_metrics(account_id, location_id, date)` and `daily_category_metrics(account_id, location_id, date, category)`.

### 10.2 `weather`

`account_id`, `location_id`, `date`, `temp_forecast`, `temp_actual`, `rain_forecast`, `rain_actual`, `wind`, `condition`, `forecast_made_at`.

### 10.3 `events`

`account_id`, `location_id`, `date`, `event_name`, `event_type`, `impact_score`, `source`, `confidence`.

### 10.4 `recommendations` (the attribution backbone)

| Column | Notes |
|---|---|
| `recommendation_id` | Immutable id for audit and replay |
| `account_id`, `location_id`, `date`, `category` | One recommendation per category per target date |
| `recommended_prep` | What we told them to prep |
| `demand_p50`, `demand_p_lower`, `demand_p_upper` | The demand distribution, not just a point |
| `service_quantile` | The operating quantile used (for example 0.78) |
| `prepared` | What they actually prepped (joins to `daily_category_metrics`) |
| `adhered` | `abs(prepared − recommended_prep) ≤ max(2, 0.10 × recommended_prep)`, measured against the recommended prep (the `q*` quantity), not the demand range |
| `override_delta` | Signed `prepared − recommended_prep`: size and direction of the override, for attribution (§14) |
| `model_version` | Which model or ruleset produced it |
| `input_snapshot_id` | Hash or id of the inputs available at generation time |
| `config_snapshot_id` | Hash or id of the economic settings and feature flags used |
| `generated_at` | |

> Without `recommendations` we can never show Dial In caused an outcome; the tool's advice would be tangled with the owner's judgement and the weather.

### 10.5 `category_economics`

`account_id`, `location_id`, `category`, `retail_price`, `unit_cogs`, `salvage_share_default`, `attached_drink_margin`, `attach_and_balk_rate`, `service_quantile`, `effective_from`, `effective_to`.

This is where the business logic lives. `service_quantile` comes from `Cu` and `Co` (§11.3), is stored with effective dates, and is copied into each recommendation so past advice can be audited after prices or recipes change.

### 10.6 Data-quality rules (enforced)

- `sold ≤ prepared`, always. A violation means bad input or a POS mismatch: flag it, don't ingest it silently.
- Counts are non-negative integers. Fractions, negatives or missing category rows are rejected before they reach the model.
- `sold_out` is derived, not trusted blindly. The default rule is `sold ≥ prepared − ε` (§12). A POS out-of-stock event or a manual correction can override it, and the override source is stored.
- Missing daily input: set `input_source = imputed`, impute `prepared` from the recommendation, and exclude the day from training the censoring logic (the true cap is unknown). Never treat a skipped day as zero.
- Closed days (`is_open = false`) are excluded from the demand series.
- Regime breaks (menu, hours or ownership change) are flagged through a `menu_version` or config change, and the model down-weights history before the break (§16).
- Late corrections don't erase history. They update the canonical row and append before and after values to a `data_corrections` audit log, so model changes can be explained later without making every query version-aware.

### 10.7 Authentication and access (login-gated)

The app requires login; there's no anonymous access to data. The pattern mirrors the sibling `decant` app on purpose, to reuse what's proven:

- Auth: `streamlit-authenticator`, with per-user credentials, password hashes in `secrets.toml` or Streamlit secrets (never plaintext, never committed) and a cookie-backed session with expiry. Managed auth (Supabase Auth, Clerk, Auth.js or similar) is a later upgrade once file-based credentials aren't enough.
- No guest mode for data. Unlike decant's optional read-only guest, Dial In has nothing useful to show without an account's own history, so unauthenticated users stop at the login wall. A logged-out demo view (synthetic café) is a separate read-only fixture, never real tenant data.
- Session to tenant, demo path: in the current demo, each credential in Streamlit secrets maps to one `account_id`. The mapping is server-side config, not a browser parameter.
- Session to tenant, database path: the schema also has `account_members(auth_subject, account_id)` for a later database-owned mapping. If used, the lookup must run through a trusted auth or admin path the browser can't influence and that can't accidentally bypass tenant checks. Don't keep both mappings as competing sources of truth.
- Every data call is account-scoped. After login the app uses exactly one server-resolved `account_id`; every read and write filters on it, and every transaction sets the matching RLS account setting.

### 10.8 Tenant isolation and training-data governance

> Requirement: historical data is never shared between accounts, but the platform may use it to train models. Both hold only if the serving path and the training path are separate and governed differently.

Serving path, strict isolation (what a tenant can read):

- Every query filters on the session's `account_id`, so a café only reads its own rows. Two layers enforce it, as decant does with its double filter:
  1. Application layer: one data-access module adds `WHERE account_id = :session_account_id` to every read and write, with no raw table access anywhere else.
  2. Database layer: Postgres row-level security keyed on a session-scoped account setting (`app.current_account_id`), so isolation holds even with an app bug. No real tenant data is loaded until this works; the synthetic demo proves the pattern first on the chosen Postgres target.
- No cross-account reads in the product, ever. Multi-location benchmarking (§15 phase 7) compares locations within one `account_id` only.

Training path: we reject blanket "train on everyone's data". The model has three layers, governed differently, because the value of pooling is concentrated and fades while the trust cost is permanent.

Status: this is the target governance design for real data. The estimator and the privileged offline training job exist (`src/dialin/shared_environment.py`, `scripts/train_shared_environment.py`): they read only the anonymised `shared_layer_features` view, output parameters and refuse sparse segments. The two-account synthetic demo is too sparse to fit a layer on purpose, so the job reports that, and the engine uses the fixed demo weather, event and season rules unless given a fitted layer.

| Layer | What it estimates | Trains on | Why |
|---|---|---|---|
| Core demand (baseline level, attach rate, weekday shape) | The café's identity | That café's own data only (POS backfill at signup plus ongoing) | Trust-sensitive ("you're helping my rival"), and pooling adds little once the café has about 8 weeks of its own history. No cross-account dependency. |
| Environment response (weather, event and seasonality elasticities) | Generic physics, not identity | Pooled, anonymised aggregates across consenting accounts | One café sees 2 or 3 heatwaves and maybe one marathon a year, too few to estimate; the pool sees hundreds. Low trust sensitivity. This is the only real, lasting network effect. |
| Cold-start level prior (a new café with no POS history) | A starting baseline before the café has data | Pooled, opt-in only, conditioned on segment, country and footfall band | Needed only for the minority without backfill (assumption register row 4); fades to zero as the café's own data arrives. Wide ranges, Low confidence flag. |

- The default is own data plus the shared environment layer. Cross-account level pooling is opt-in, not opt-out (reversed from v2.0 on purpose). Most cafés never need it, because their POS backfill covers cold start.
- A privileged offline training job (platform admin role, never a user session) fits the environment layer and the cold-start prior. It outputs parameters only (elasticity coefficients, segment baselines), never another tenant's raw rows, numbers or name. A tenant benefits from others only through the weights of the shared environment layer.
- For users, the environment layer is "a benchmark built from cafés like yours", not "we use your sales data". That's honest and easier to understand.
- Privacy: training data is operational counts (pastries, drinks, weather, events), with no PII and low sensitivity. The remaining memorisation risk (a near-unique café in a sparse segment) is limited by training only on segments with at least N consenting accounts. Differential privacy or k-anonymity is the hardening step for sparse segments: named, not built at MVP. [Likely sufficient for non-PII counts.]
- Consent, in plain language: "Your sales data is private to your account and is never shown to other accounts. We use anonymised, aggregate patterns to improve the shared weather and event benchmark. You can opt out of contributing and still use the app." Opted-out accounts still use the shared layer; they just don't feed it.

Data model additions:

- `accounts`: `account_id`, `plan`, `contributes_to_shared_layer` (bool, default true), `cold_start_pool_opt_in` (bool, default false), `pos_backfill_months` (int, feeds assumption register row 4), `created_at`.
- `account_members`: `auth_subject`, `account_id`, `created_at`, for the database-owned auth-to-tenant mapping.
- `locations`: `account_id`, `location_id`, `name`, `timezone`, `city`, `country`, `open_days`, `service_capacity_hint`, `created_at`.
- `data_corrections`: `account_id`, `location_id`, `date`, `category` (nullable), `field_name`, `old_value`, `new_value`, `corrected_by`, `corrected_at`, `reason`.
- An `account_id` foreign key on every operational table (§10.1 to §10.5).
- All cross-account aggregation goes through a separate `shared_layer_features` view, readable by the platform admin role and no tenant role.

### 10.9 Data operations requirements

Product requirements, not back-office extras:

- Connections: app code uses `DATABASE_URL`; migration and seed code use a separate admin connection. The app must never run with schema-owner credentials.
- Lineage: every recommendation stores `model_version`, input snapshot, economics config snapshot, weather forecast timestamp and generation time.
- Freshness: after end-of-day submit, the next-day recommendation appears in the same session. If generation fails, the app shows the last valid recommendation with a clear stale flag.
- Monitoring: daily checks on missing input rate, validation rejects, sellout and censoring rate, calibration drift, weather forecast error and cross-account access test results.
- Reproducibility: any past recommendation can be replayed from stored inputs and config. If it can't be replayed, it can't be used in ROI attribution.
- Access audit: reads and writes of tenant data are logged with user, account, location, table and time. This matters more once multi-location accounts arrive.

### 10.10 Opening hours and intraday data (not needed for v1)

The MVP works at daily grain on purpose, but the intraday path must stay in view: sellout time and demand shape connect "what should I prep tomorrow?" to "when will we run out?".

Don't fake it in production. Intraday claims need timestamped POS rows or a clear synthetic or demo label.

Future schema:

- `location_hours`: `account_id`, `location_id`, `weekday`, `opens_at`, `closes_at`, `service_notes`, `effective_from`, `effective_to`. Separate from `open_days`, since Saturday hours can differ from Tuesday's.
- `daily_daypart_metrics`: `account_id`, `location_id`, `date`, `daypart_start`, `daypart_end`, `drinks_sold`, optional category sales. Filled only with POS timestamps or in a clearly labelled synthetic demo.
- `sellout_time_estimates`: `account_id`, `location_id`, `date`, `category`, `estimated_sellout_at`, `observed_last_sale_at`, `source`, `confidence`. Keeps an observed POS timestamp apart from a modelled estimate.

These unlock: "sweet pastries likely sell out by 12:15 if you prep 44", demand curves adjusted for opening hours, lost-sales estimates for the remaining hours after a sellout, and staffing suggestions from traffic shape (roadmap phase 4).

Guardrail: without timestamped sales, the app may show day-level sellout risk but must not imply an exact sellout time.

## 11. Forecasting and decision strategy

The forecast produces a demand distribution, and a separate decision layer turns it into a prep quantity. Keeping them apart is the point.

Cadence and horizon: generation is event-driven, not on a clock. When the operator submits end-of-day numbers (§7), the engine runs, and the next day's recommendation is produced at once and saved, readable from then on. It relies on a next-day weather forecast (about 12 to 36 hours ahead), with forecast error carried into the demand range (§11.4) and the forecast vs actual gap stored (§10.2) and monitored. It reruns if a materially newer forecast arrives before prep.

### 11.1 V1: rules-based (MVP)

- Inputs: weekday, month, weather forecast, attach rate, trailing same-weekday averages, event flags.
- The mean: expected demand = expected traffic (from drinks) × attach rate, with multiplicative weather, event and season adjustments. In the synthetic demo these are fixed demo rules; on real data they can be replaced by the shared environment layer (§10.8) once its training job runs. Both traffic and attach rate are fitted on the café's own censoring-corrected history (§12). Attach rate must use de-censored pastry demand, not raw `sold`, or it's biased down on exactly the sellout days and brings censoring back in one level up (§12).
- From a point to a distribution (which §11.3 needs): a point forecast has no percentile, and the newsvendor decision needs one. Demand is a small integer count, so it's modelled as Negative Binomial, not Gaussian and not Poisson (pastry demand is overdispersed; variance exceeds the mean). The mean comes from the point method; dispersion is fitted from past forecast residuals in the same condition bucket (segment × weekday band × weather bucket). Thin buckets fall back to empirical residual quantiles. The recommendation is the `q*` quantile of this distribution (§11.3), rounded up, because a fraction of a pastry is a whole pastry.
- Demo vs Fadri boundary: the synthetic demo may use the lighter comparable-day method from the companion design doc. The real Fadri path must use the §12 censoring-aware method, or stay in shadow until the lighter method passes the §6.4 gate on Fadri's held-out data, so the demo shortcut never becomes an unexamined real-data shortcut.
- Why first: it's explainable, fast, stable, debuggable and good enough to beat the naive baseline. Sophistication isn't the bottleneck; data discipline, censoring correction and the decision layer are. The cold-start prior is only for cafés without backfill (§13).

### 11.2 V2: machine learning (only when the data justifies it)

- Models: gradient-boosted trees (LightGBM, XGBoost) and/or hierarchical models, within the layer split (§10.8). The environment-response layer suits a pooled cross-café model (lots of data, low sensitivity). The core demand layer stays per café (or per account for multi-location), shrinking only toward that account's own sites.
- Hard precondition: one café produces about 250 to 320 usable rows a year (about 6 open days a week). Tree models with 25 to 35 features on a few hundred rows overfit badly, so a café-private ML core is justified only once it beats both the V1 rules model and the naive baseline on held-out pinball loss. Until then, V1 rules plus the pooled environment layer are the default. [Certain; a data-volume constraint, not a preference.]
- Features: the §13 signals plus censoring-corrected demand labels.

### 11.3 V3: probabilistic forecast and the newsvendor decision (the core)

The recommendation isn't the mean or median. Prep is a newsvendor decision: the quantity that minimises expected cost given asymmetric over and under costs.

```text
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

Two corrections to a naive newsvendor, both of which move `q*` a lot:

- `Cu` includes the attached drink, not only the pastry, consistent with §2: a stockout also costs the coffee that would have come with it. The attach-and-balk rate is the share of pastry buyers who also skip a drink when the pastry is gone, estimated per café with a conservative default.
- `Co` is net of salvage. A binned croissant costs full COGS; a discounted or staff-eaten one costs less. Items that keep for days (cookies) have high salvage and a much lower `q*`.

A hypothesis, not yet a fact: food stockouts may lower drink sales, because a customer who wanted coffee and a croissant may leave if the croissant is gone. If that's material, `drinks_sold` isn't fully uncensored on food-sellout days either. The model estimates it through `attach_and_balk_rate` and treats it as uncertain until real data or owner evidence supports it. Don't hard-code it as if every missed pastry also meant a missed drink.

For the owner (never shown the maths): "running out costs you more than throwing out, so we tell you to make a bit extra: the amount that loses you the least money over time." `Cu`, `Co`, attach-and-balk and salvage are set per café at onboarding (with sensible defaults) and shown as one "waste vs run-out" slider the owner can adjust by feel.

### 11.4 Uncertainty (the honesty layer)

The demand range must include error from forecast inputs, not only demand noise, because demand is predicted from forecast weather and estimated events, which are sometimes wrong. On days with volatile or low-confidence inputs (an uncertain storm, an ambiguous event), the range widens and confidence drops. The model is allowed to say "I don't know, make your usual ±20%."

## 12. Censored demand (the central estimation problem)

> Not a footnote. This is why naive forecasting fails here, and the main thing that makes Dial In defensible.

### The trap

Sales aren't demand. Prep 40 and sell 40, and you sold out: real demand could have been 45, 60 or 70, and you can't see it. A forecaster trained on raw `sold` learns supply-capped sales, recommends prep close to past sales (so past prep), and never discovers the real ceiling. Under-prep looks "accurate" (you sold everything) and the model quietly repeats yesterday's mistake. A forecaster that ignores censoring converges to the café's existing error.

### The correction

1. Label each day censored or uncensored with a defined threshold. `sold_out` is set when `sold ≥ prepared − ε`, where `ε` is a small per-category tolerance (default 1 unit, configurable) for crumbs and miscounts. A real POS out-of-stock event overrides the inferred flag. Uncensored means leftovers existed (`sold < prepared − ε`), so demand is observed exactly. Censored means `sold_out`, so demand is at least `prepared`. This threshold carries real weight: too tight misses real sellouts, too loose treats normal days as censored. It's tuned per café and audited (§6.1 calibration).
2. Estimate true demand on censored days from comparable uncensored days (same weekday band, weather bucket, traffic level, event status), using the drinks-sold traffic signal and the category attach rate. Drinks show footfall even when pastries sold out.
3. Fit with a censoring-aware method. Primary: a Tobit (type I, right-censored) model on log demand, with the sellout flag from step 1 marking censored observations. A survival / Kaplan-Meier view cross-checks the upper tail. Never ordinary regression on `sold`. [Certain on the framing; Tobit is the default, revisited only if it underperforms the cross-check on real data.]
4. Report the consequence honestly: estimated lost units and margin on sold-out days, as a range, feeding the combined cost metric (§6.2). Never a falsely precise "you lost exactly 12 sales".

### When the correction is weak

Censoring correction can't recover a tail it has never seen. A café that sells out chronically has almost no uncensored high-demand days, so the upper quantile (`q*`, §11.3) is extrapolated with wide error, on exactly the high-demand days that matter. Three responses, in order:

1. Detect it. Track each category's censoring rate (share of days sold out). Above a threshold (say, more than 40% of comparable days), flag the upper quantile as low confidence.
2. Widen, don't fake. When the tail is unobserved, the range widens and confidence drops (§11.4) instead of giving a confident extrapolation.
3. De-censor on purpose. On a small, controlled share of low-risk days, the recommendation deliberately preps above recent sellout levels to see where demand really tops out. It's active experimentation to learn the tail, with the extra waste capped and disclosed. It's the only way a chronically under-prepping café ever finds its real ceiling, and it's what breaks the under-prep loop instead of re-fitting it.

### The traffic proxy caveat

"Drinks are uncensored" holds on ordinary days but can fail two ways. One barista, a long queue and walk-outs make drink sales throughput-censored on the busiest days. And food stockouts may cut drink purchases if some customers wanted coffee and food and abandon the whole order. So: (a) treat very high-traffic days as possibly censored on drinks too, (b) mark food-sellout days as possibly depressing drinks when `attach_and_balk_rate` isn't zero, and (c) lean on outside footfall signals (weather, events, day of week) rather than drinks alone when traffic nears the café's observed service ceiling or food sold out early. [Likely material for high-volume and brunch-heavy cafés.]

### Intraday honesty

"Sold out at 11:15, demand continued to 14:00" needs timestamped sales. If the POS gives `time_last_*_sale`, the lost-sales tail is estimated from the remaining-hours traffic curve. If not, that claim is disabled and only day-level censoring is used. No invented intraday detail.

## 13. Forecast features and cold start

Feature families:

| Family | Features |
|---|---|
| Traffic | Drinks sold (today, lag 1 day, lag 7 days), rolling 4-week same-weekday mean, attach rate (pastries per drink) and its stability |
| Weather | Temperature, rain, wind, condition, whether outdoor seating works; forecast and actual both stored |
| Events | Markets, marathons, festivals, concerts, fixtures, with impact and source confidence |
| Calendar and season | Weekday, month, quarter, public and school holidays, bridge days, tourism season, Christmas |

### Cold start is smaller than it looks

The instinct is that a new café has zero rows, so it must borrow from other cafés. Mostly false: most cafés arrive with 1 to 2 years of their own POS history (Square, Toast and Lightspeed keep it). It's backfilled at signup, so the typical new café trains its own core model from day one without any other account's data. Cold start is a minority case. [Likely, depending on POS export coverage, assumption register row 4.]

What drives the recommendation, by situation:

| Situation | Core demand (level, attach) | Environment response (weather, events) | Confidence |
|---|---|---|---|
| Has POS backfill (the common case) | The café's own backfilled history | Shared environment layer (§10.8) | Medium to high from day 1 |
| No backfill, 0 to 8 weeks | Opt-in cold-start prior (segment, country, footfall band) plus a 3-question setup, shrinking toward own data as it arrives | Shared environment layer | Low, with wide ranges |
| 8+ weeks, any café | The café's own data dominates | Shared environment layer (still pooled; one café never sees enough rare events) | High |

Two things never change. The environment-response layer is always shared: even with three months of data, a café can't estimate its own heatwave or marathon response. And the core baseline stays private to the café.

That's why `account_id` and `location_id` are mandatory (§10). The cross-café benefit flows only through shared parameters (§10.8): a new café inherits an elasticity or an opt-in prior, never another café's rows. Tenant isolation and pooling don't conflict; they sit on opposite sides of the serving/training split, and only the low-sensitivity environment layer crosses it.

## 14. Measurement and attribution (how we learn if it works)

A decision tool that can't evaluate its own recommendations teaches the wrong lesson. The goal isn't a sales proof; it's to learn whether the model would have improved prep decisions under honest uncertainty.

1. Baseline period (2 to 4 weeks) in shadow mode: recommendations are generated and logged, but the owner preps as usual. This sets the café's own pre-Dial-In waste, sellout frequency and combined cost. The friction trade-off: in shadow there's no acted-on recommendation to pre-fill the end-of-day input (§7), so `prepared` is entered by hand and completion dips during exactly the period that needs clean data. Pre-fill the shadow input with the café's own trailing same-weekday prep and keep the baseline short.
2. Naive baseline benchmark: the model must beat last week's same weekday and the trailing 4-week same-weekday average on pinball loss before it influences decisions (§6.1).
3. Real-data comparison, stated honestly: for Fadri the main readout is within the café: recommendation vs actual prep, observed outcome and modelled cost. A cross-café rollout design is optional future context.
4. Adherence-conditioned readout: `recommendations.adhered` is logged, so outcomes on days the owner followed the recommendation can be compared with days they overrode it. That's the cleanest within-café causal signal short of a formal experiment.
5. Headline impact metric: the change in total expected mis-prep cost per week (waste COGS plus estimated lost margin), with a confidence range, never a bare percentage.

### 14.1 Fadri measurement protocol

Before using real Fadri data for decisions, write down:

- Baseline and live windows. Default: 2 to 4 weeks of shadow plus at least 4 weeks live, longer if closures or events leave too few usable open days. It isn't a formal power guarantee or enough by itself to prove calibration; it's the minimum learning window before deciding whether to continue.
- The owner's tolerance: the owner sets the waste vs run-out preference in economics setup (§10.5, §11.3). A recommendation that breaks that preference isn't called better.
- The attribution view: report observed waste proxy, sellout frequency and combined expected cost together. Reporting only the best-looking one is cherry-picking.
- A decision log: every override gets an optional reason (`weather felt wrong`, `supplier issue`, `large order`, `owner judgement`, `other`). Overrides are signal, not failure; they show what the model missed.

## 15. Future roadmap

Broader than the first build on purpose, so the idea can be judged honestly instead of narrowed too early.

| Phase | Scope |
|---|---|
| 1A: decision demo completeness | Show the weather forecast, event list, season label, confidence reason and top drivers in the recommendation UI. The engine needs these inputs anyway; hiding them makes the advice feel arbitrary. |
| 1B: attribution basics | Fill `prepared`, `adhered` and `override_delta` after closeout, capture override reasons, and show adherence-conditioned results separately from general scorecard claims. |
| 1C: economics setup | Economics confirmation and a "waste vs run-out" control backed by `Cu`, `Co`, salvage share, attached-drink margin and attach-and-balk defaults. Until confirmed, label recommendations as using defaults. |
| 1D: data-quality workflows | Closed days, late corrections, bad-input repair, menu-version changes and correction history in the UI. Without these, the model learns from dirty data. |
| 1E: honest measurement | Naive baselines, pinball loss, calibration, bias, censoring rate, combined expected cost and synthetic vs real labels. Revenue or savings shown as estimates with assumptions, never "generated revenue". |
| 1F: weather, events and season | Real weather API, forecast vs actual storage, semi-manual event confirmation, public and school holidays, bridge days, tourism season and low, mid or high season labels. Automatic hyperlocal events stay a risk until source coverage is proven. |
| 2: intraday | Opening hours, hourly or daypart demand curves, sellout-time prediction, remaining-hours lost-sales estimates and service-capacity or queue-balking detection. Needs timestamped POS data; synthetic-only display is fine for demos if labelled. |
| 3: POS backfill and import | CSV import first, then POS APIs. `sold` becomes imported; `prepared` stays manual. Measure timestamp coverage before enabling intraday claims. |
| 4: staffing | Turn traffic forecasts and demand curves into shift suggestions. Secondary to prep until there's enough timestamped traffic data. |
| 5: ingredients | Break category or SKU prep into raw inputs through recipe mappings. |
| 6: inventory | Ordering and par levels. Adjacent, not the core use case. |
| 7: multi-location benchmarks | Compare locations within one account only; cross-account benefit stays in shared parameters, never raw rows. |
| 8: SKU-level prep | Move from sweet and savory to individual products. Categories are an MVP simplification; real operators will eventually ask "which pastry?", not only "how many sweet?". |
| Long range: shared environment model | Pooled weather, event and season elasticities with consent, minimum segment sizes, sparse-segment privacy checks and opt-out monitoring. |

## 16. Edge cases and regime changes

- Closures and holidays: `is_open = false`, excluded from the series.
- Menu changes: a new or removed product bumps `menu_version`, and pre-change history is down-weighted for the affected categories.
- Hours or ownership changes: treated as regime breaks, with pre-break history down-weighted and ranges widened. If the break invalidates most history, fall back to the cold-start path (§13: remaining own data plus the shared environment layer, and the opt-in prior only if there's truly no usable history).
- Bad manual input: caught by the `sold ≤ prepared` rule (§10.6) and flagged for one-tap correction.
- POS outage or missing import: fall back to traffic priors and set confidence to Low.

## 17. Value sizing (not a pricing plan)

This is modelling discipline, not a price list. If the expected value is tiny, Dial In may still be an interesting forecasting exercise but won't matter operationally. The framework helps decide whether the problem is worth attention for Fadri-style cafés.

Size the addressable pool first, then apply one forecast-driven reduction. Don't add two independent savings: that double-counts the §6.2 tradeoff.

Baseline monthly cost of mis-prep for an example single-location café (about 80 pastries prepped a day):

| Component | Baseline (illustrative) |
|---|---|
| Waste: about 12 units a day discarded at €0.90 COGS × 30 | about €324 |
| Lost margin: about 8 sellout days × about 10 unmet units at €2.60 | about €208 |
| Total addressable mis-prep cost | about €532 a month |

A better forecast pulls the whole waste vs stockout curve inward. The newsvendor quantile (§11.3) only picks where on the curve the café sits (more waste or more stockouts); it doesn't reduce the total. Accuracy does. A credible combined reduction of 20 to 30% on the €532 pool saves about €105 to €160 a month. The higher order value (the coffee that comes with a recovered pastry sale) is real upside, deliberately left unsized.

The 20 to 30% is an assumption to test with real or synthetic replay, not a promise. Pricing can be revisited if this ever becomes a commercial product. Today the question is simpler: does the model cut expected mis-prep cost enough to be worth using?

### 17.1 Value validation checklist

The value logic is a framework, not evidence. Before trusting any savings estimate, collect:

- Actual daily prep, sales and leftover handling by category.
- Retail price, unit COGS, salvage behaviour and attached-drink margin.
- Open days, sellout days and the owner's estimate of missed demand.
- Whether the owner values saved attention, less staff stress and better customer experience enough to count them. If not, leave them out.
- Whether baked goods are central enough that food sellouts change the day, not just the snack display.

## 18. UX requirements

- Mobile first. Owners use a phone, often one-handed, mid-service.
- Fast. Page load under 3 seconds; the recommendation renders first.
- Simple. No dashboard or report on the landing screen and no analytics jargon. The "why" is one tap away, not in the owner's face.
- Honest. Confidence and range are always shown. A single number without a range is forbidden, because it implies certainty the model doesn't have.

## 19. Non-goals

Dial In is not an inventory system, an accounting system, a POS replacement, a workforce-management platform, a BI or reporting tool, or a recipe manager.

It does one job: help a mixed-focus specialty coffee place decide how much fresh food to prep, then learn honestly whether that advice beat the baseline.

## 20. Open questions and assumptions

| # | Assumption or open question | Risk if wrong | How we'll close it |
|---|---|---|---|
| 1 | Drinks sold is a reliable, nearly uncensored traffic proxy | The traffic-to-demand chain weakens | Check attach-rate stability on pilot data before trusting it |
| 2 | Owners will enter `prepared` daily | Censoring logic degrades | Pre-fill and one-tap confirm; monitor completion; degrade gracefully |
| 3 | Per-café `Cu`/`Co` can be captured at onboarding | Wrong service level, systematic mis-prep | Sensible category defaults; owners tune by feel with the "waste vs run-out" slider |
| 4 | Most signups have exportable POS backfill (1 to 2 years); this is what removes most cold start | If under about 70% have backfill, cross-account cold-start pooling matters far more than §13 says | Measure `pos_backfill_months` in the first cohort; if low, reconsider the opt-in default for the cold-start prior |
| 5 | The shared environment layer beats per-café weather and event estimates | If one café's rare-event signal is good enough alone, the only lasting network effect disappears | Compare pooled vs café-only elasticities on held-out rare-condition days |
| 6 | The single-location use case is valuable enough to justify attention | The model may be interesting but not useful | Validate §17 with Fadri-style economics before spending time on wider use |
| 7 | GUC-based RLS works cleanly with `streamlit-authenticator` on the chosen Postgres | If not, tenant isolation needs rework before real data | Prove it with the synthetic demo on local Postgres and Neon: app role, `SET LOCAL app.current_account_id` and cross-account query tests |
| 8 | Customers accept the shared environment layer framed as a benchmark | Trust pushback; opt-outs shrink the pool | Plain-language clause and the `contributes_to_shared_layer` opt-out (still use it, don't feed it); monitor opt-out rate |
| 9 | The shared layer won't memorise sparse segments | Indirect leakage of a near-unique café | Train only on segments with at least N consenting accounts; DP or k-anonymity for sparse segments |
| 10 | POS timestamps are available often enough for intraday | Phase 2 (hourly) is blocked | Check timestamp coverage in Fadri data and any later real datasets |
| 11 | Hyperlocal events can come from an "automatic" feed | §9 oversells; there's no clean global API for a town-square market | Semi-manual events at MVP (owner confirms a short list); automate only with a reliable source; size coverage before promising |
| 12 | Chronic-sellout cafés will accept the de-censoring probe (occasional deliberate over-prep) | Waste-averse owners reject the tail-learning mechanism (§12) | Make the probe opt-in and bounded, framed as "we'll occasionally test a bit higher to find your real ceiling", with capped extra waste |
| 13 | Fadri's real operating bands are close enough to seed a credible synthetic demo | Fake-looking data hurts trust before the product is discussed | Get rough drinks per day, attach, waste and sellout ranges; if unavailable, label Fadri fictionalised and don't imply realism |
| 14 | Category-level recommendations are enough for the MVP | Owners may ask "which pastry?", not only "how many sweet?" | Track override reasons and sales mix; move to SKU level only if category advice is too blunt |
| 15 | The simplified demo de-censoring shows behaviour well enough | The demo teaches the wrong modelling habit | Keep it synthetic-only; the real Fadri path must pass §6.4 before recommendations are trusted |
| 16 | The owner can supply or approve economics | `q*` becomes fake precision | Store defaults apart from confirmed values; lower confidence until confirmed |
| 17 | Weather APIs are available, cheap and reliable enough for daily use | Missing or stale forecasts make recommendations look random | Store the forecast timestamp, fall back to seasonal normal, monitor weather error, show Low confidence when stale |
| 18 | Local event data can stay current without annoying owners | Stale or wrong event effects; false lifts hurt trust | Start with owner confirmation of a short candidate list; automate only sources with proven local coverage |
| 19 | Low, mid and high season labels are understandable and useful | Labels become hand-wavy narrative, not model signal | Tie labels to configured calendar and tourism periods and show their measured historical lift |
| 20 | Opening hours are stable enough to model intraday demand | Hours changes create false demand curves and sellout-time claims | Version `location_hours`; treat hour changes as regime breaks |
| 21 | Synthetic demand curves help demos without misleading users | The demo implies precision production lacks before POS timestamps | Label synthetic curves clearly and disable real intraday claims without timestamped POS data |
| 22 | Estimated revenue and savings can be explained without overclaiming | Users read modelled lost sales as proven money | Report observed waste proxy, sellout frequency and combined expected cost with assumptions and uncertainty |
| 23 | Recommendation hashes are enough for replay | Hashes prove identity but not replayability if raw snapshots are missing | Store full input and config snapshots, or reconstructable snapshot tables, before claiming audit-grade replay |
| 24 | Override reasons will be entered honestly | Owners skip reasons or pick "other", weakening attribution | Keep reason capture optional and one tap; treat missing reasons as a sign of UX friction |
| 25 | Food stockouts reduce drink sales through basket abandonment | If true, drinks aren't a clean traffic proxy on sold-out days; if false, stockout cost is overstated | Estimate `attach_and_balk_rate` conservatively, compare drink sales on similar food-sellout and non-sellout days, and treat it as uncertain until validated |
| 26 | The target shop treats baked goods as a real part of the offer, not a minor extra | If food is incidental, the product solves a small annoyance, not a paid problem | Qualify early users by food revenue share, weekend sellout frequency, sellout time, waste pain and whether food stockouts affect basket size or repeat visits |
| 27 | Customer counts aren't needed in the first version | Without footfall, drinks stay the traffic proxy and may miss non-buyers or walk-aways | Add customer, door or order counts later only if drinks and POS history can't pass the model gates |

## 21. Build readiness gates

The checklist that moves the project from an interesting idea to something worth testing with synthetic data and, later, Fadri's real data:

1. Schema gate: account, location and category grain in place; RLS test passes; `recommendations` stores lineage and economics snapshots.
2. Data gate: validation rejects bad counts; missing inputs are imputed but excluded from censoring training; corrections are audited.
3. Model gate: the rules model beats both naive baselines on pinball loss, is calibrated, and shows no systematic bias (§6.4).
4. Usefulness gate: Fadri-style economics and operational value justify the attention, with uncertainty shown (§6.5, §17.1).
5. Honesty gate: every claim keeps observed facts, modelled estimates and synthetic demo behaviour apart.

Failing a gate doesn't kill the project. It says what the real problem is: data capture, model quality, tenant safety or operational value.

## 22. Positioning

Dial In helps a mixed-focus specialty coffee place decide what to prepare tomorrow. It combines the owner's instinct with a model that respects how the decision really works: running out costs more than throwing out, and you can't manage demand you never observed.

"What should we prepare tomorrow?" Everything else comes second.

## 23. Implementation status and backlog

What's built, against the requirements above. `docs/Architecture.md` covers how it works; `README.md` has the commands.

Built: the schema, tenant isolation (RLS, with database-backed isolation tests in CI), and the V1 decision engine: censoring-corrected attach rate, Negative Binomial demand distribution, newsvendor prep quantity, confidence and risk flags, and replayable snapshots. Both censoring methods exist and are chosen per call: the demo comparable-day method and the real-data right-censored Tobit (§12), with Tobit advisory until it clears the §6.4 gate. Also built: the de-censoring probe (§12); the honest-measurement metrics (§6: pinball loss, the two naive baselines, calibration, signed error, censoring rate, expected mis-prep cost, model gates); attribution and the pilot report (§14); and the pooled environment-layer estimator with the cold-start prior (§10.8, §13). Weather comes from outside (§1.1): Open-Meteo forecasts and ERA5 reanalysis outcome proxies, written to the `weather` table and read back through the existing staleness and confidence handling. The engine never hardcodes the two categories, so SKU-level prep is a data change, not a rewrite (§15).

Still synthetic or demo-only: sales, traffic, events, economics, hours and usage/adherence stay synthetic until a real café uses the app, and must read as advisory (§1.1). Historical demo weather stays synthetic on purpose. POS import is CSV only, and auth is `streamlit-authenticator`, not managed. The shared environment layer has an estimator but isn't fitted; the two-account demo is too sparse, by design.

Not built yet: a weather re-fetch when a newer forecast arrives before prep (§11); real event, holiday and tourism feeds with owner confirmation (§9); a Tobit vs comparable-day comparison on Fadri's held-out data, with a survival cross-check on the upper tail (§12); POS APIs and timestamp coverage for production intraday claims; a SKU-level UI; and the operational hardening below.

### Before a real-data pilot

Roughly in priority order. Most of the acceptance detail is already in §6.4, §6.5, §14.1 and §18.

1. Operate safely: database backups with a tested restore; monitoring and alerts for failed refreshes, stale weather and migration failures; a managed user lifecycle (file-based login is fine only for a tightly controlled single-tenant pilot, not multi-tenant); and a hard guarantee that demo refresh and synthetic truth can never run against a real tenant.
2. Measurable pilot acceptance: complete and record a restore drill; route every refresh, migration and stale-weather alert to a named owner with a runbook; hold warm p95 load under 3 seconds for Today and p95 closeout-to-recommendation under 5 seconds for seven operating days in a row. Missing closeouts or weather must degrade visibly, never silently.
3. Prove the decision on real data: a shadow window at a real café, recommendations frozen before the outcome, Tobit and comparable-day compared against both naive baselines on the same held-out dates, and nothing driving prep until the §6.4 gates clear.
4. Prove the workflow and value: the §6.3 usage targets and the §6.5 value gate, reported together and honestly (waste proxy, sellout frequency, expected cost with its uncertainty, adherence), plus the question that decides whether it can be sold: would the owner keep paying? The owner summary is the commercial view; Advanced analysis is the audit trail behind it.
5. Make onboarding repeatable: operator-safe location, hours and economics setup; reusable POS mappings with re-import and reconciliation; and configurable category or SKU closeout instead of the hard-coded sweet and savory fields.

Staffing, ingredients, inventory and cross-location benchmarks stay out until a real café clears both the model gate and the pay-again gate.
