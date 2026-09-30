# Dial In architecture and method

How the synthetic demo works: the engineering view, not a replacement for the PRD. Dial In started as a learning project and a demo built for Fadri; the README has the current product status.

## What the demo does

Dial In answers one daily question for a café:

> How much fresh food should we prepare tomorrow?

The demo runs on generated synthetic data. That shows the workflow, the data shape, the censoring problem and the decision logic. It can't prove the app saves money in a real café; that needs the future Fadri data path.

The scaffold includes the paths below. Local and hosted RLS still need database-backed checks before any real tenant data is loaded.

- Login-gated Streamlit UI.
- Two synthetic demo tenants: `acct_fadri` and `acct_dummy`.
- A planned real-data path for Fadri Café with the same account-scoped workflow.
- Account-scoped Postgres reads and writes through repository helpers.
- Row-level security policies on `app.current_account_id`.
- Synthetic observed data loaded into Postgres.
- Planted truth kept on disk only, never loaded into Postgres.
- End-of-day closeout entry.
- Immediate next-day recommendation.
- Replay controls for the synthetic history.

## Main components

### Streamlit app

Entry point: `app.py`. It handles:

- Login through `streamlit-authenticator`.
- Mapping a username to an internal `account_id`.
- Choosing the closeout date.
- Showing the recommendation for `closeout_date + 1`.
- The v1 manual closeout: drinks sold, sweet sold, sweet prepared, savory sold, savory prepared.
- Saving closeout rows.
- Running and saving recommendations.
- An observed-only synthetic scorecard.

The username isn't the account id. In the current demo, Streamlit secrets bind each username to one `account_id` (for example `demo` to `acct_fadri`, `dummy` to `acct_dummy`). `account_members` exists for a later database-owned mapping but must not become a second source of truth.

### Database

Migrations are in `migrations/`. The schema is plain Postgres, with no Neon, Supabase or other provider-specific APIs.

Main tables: `accounts`, `account_members`, `locations`, `daily_metrics`, `daily_category_metrics`, `weather`, `events`, `category_economics`, `recommendations`, `data_corrections`. Every operational row is scoped by `account_id` and `location_id`.

### Tenant isolation

Two layers.

Application layer: repository functions always filter by `account_id`, the app takes `account_id` from the login session, and it never trusts an account id from the browser.

Database layer: RLS is on for tenant tables. Each account-scoped transaction runs:

```sql
SELECT set_config('app.current_account_id', '<account_id>', true);
```

RLS policies compare each row's `account_id` with that setting, so if the app forgets a filter, Postgres still blocks other accounts' rows.

### Synthetic generator

Code: `src/dialin/generator.py`. It writes two outputs:

| Output | Contents | Loaded into Postgres? |
|---|---|---|
| `data/generated/observed/` | Accounts, locations, daily metrics, daily category metrics, weather, events, category economics | Yes |
| `data/generated/truth/` | Planted demand: true drinks, true category demand, lost units, waste units | Never |

The app must never read truth files. That's an honesty boundary, not a convenience.

## Data flow

1. Run migrations against Postgres.
2. Generate synthetic data.
3. Check realism and truth separation.
4. Load observed data into Postgres.
5. Start Streamlit.
6. Log in as a demo user.
7. Submit a closeout day.
8. Generate tomorrow's recommendation.
9. Save it in Postgres.
10. Show the saved result in the UI.

Recommendations are saved. Reopening the app shows the saved recommendation for the day after the selected closeout date; it doesn't quietly recompute a different one.

## Why censoring matters

Sales aren't always demand. If a café prepared 40 pastries and sold 40, demand might have been 40, or 55. Sales are capped by what was prepared: that's censored demand.

A naive forecast trained on raw sales learns the café's old prep ceiling. It looks accurate on sellout days while repeating the same under-prep.

The demo uses a light correction:

- If a category didn't sell out, sales count as demand.
- If it sold out, demand is lifted using comparable days that didn't sell out.
- Comparable days are same-weekday history, scaled by drinks sold.
- With too few comparable days, demand falls back to `prepared * 1.15`.

That's the demo default (`comparable_day`). The PRD's real-data method is also built: `src/dialin/censoring.py` fits a right-censored Tobit model on log demand (sold-out days are censored at `prepared`) by EM, with numpy and a centred log-drinks covariate. The engine uses it with `build_recommendations(..., censoring_method="tobit")` and records the choice in the config snapshot. Like the demo method, it stays advisory until a café's model passes the section 6.4 ship gate on held-out data (PRD 11.1).

## Forecast method

The v1 engine is `src/dialin/engine.py`. For a target date it works through these steps.

### 1. Traffic forecast

Drinks sold stand in for traffic. The forecast starts from a trailing same-weekday mean and applies weather and events:

```text
base traffic = average drinks sold on recent same weekdays
traffic forecast = base traffic * weather multiplier * event multiplier
```

Weather goes through a provider seam (`src/dialin/weather.py`) rather than being read raw. `FrameWeatherProvider` gets the target-date forecast from the `weather` table and computes its age from `forecast_made_at`. A forecast older than `STALE_FORECAST_AGE_HOURS`, or a missing row (seasonal-normal fallback), is flagged and forces Low confidence, which widens the demand range instead of trusting an old number (PRD 11.4).

Forecasts come from a real source. `OpenMeteoWeatherProvider` calls the Open-Meteo API (free, no key) for each location's coordinates. `scripts/fetch_weather.py` writes the next few days' forecasts to the `weather` table, tagged `forecast_source = 'open_meteo'` with `forecast_made_at` set to the fetch time. Once a date has passed, it backfills an outcome proxy (`temp_actual`, `rain_actual`) from the ERA5 archive. It only touches Open-Meteo rows, so the generator's synthetic history is left alone. The daily refresh fetches weather before regenerating recommendations, so a live next-day recommendation uses the real forecast, and an API failure falls back to seasonal normal. ERA5 is reanalysis, so the backfilled fields are outcome proxies, not station measurements or ground truth.

The weather multiplier lets warm weather lift traffic and rain suppress it, within bounds that prevent extreme swings. Each event has an `impact_score`, and the event multiplier is the product of `1 + impact_score`.

### 2. De-censored attach rate

Attach rate is category demand per drink:

```text
attach rate = estimated category demand / drinks sold
```

It uses estimated demand, not raw sales, so sellout days don't drag the model down.

### 3. Demand mean

```text
demand mean = traffic forecast * attach rate
```

Current categories: `sweet` and `savory`.

### 4. Demand distribution

The prep decision depends on risk, so the app needs a distribution, not a point. The demo uses a Negative Binomial: pastry demand is count data and usually more variable than a Poisson allows. Dispersion comes from recent corrected demand, with a conservative default when history is thin.

### 5. Newsvendor decision

The recommendation isn't the mean. It's the quantity that balances the cost of prepping too little against prepping too much:

```text
q* = Cu / (Cu + Co)
Cu = under-prep cost = lost pastry margin + attached drink loss
Co = over-prep cost = unit COGS after salvage
```

Running out loses pastry margin and maybe an attached drink; over-prepping loses COGS after salvage. If running out costs much more than waste, `q*` is above 0.5 and the app recommends a higher percentile than the median.

`service_quantile` is stored in `category_economics` and copied into every recommendation for auditing.

### 6. Output

Per category, the engine stores: recommended prep, p50 demand, lower and upper demand bounds, service quantile, confidence, risk flag, top drivers, model version, input snapshot hash, config snapshot hash and generation time.

## Confidence and risk

Confidence depends on history depth, recent censoring rate and missing weather. High sellout rates lower confidence because the upper tail of demand isn't well observed.

Risk flags are simple labels for the owner: `Normal`, `High demand possible`, `Stockout learning needed`. The point isn't to sound precise; it's to tell the operator when the model leans on weaker evidence.

## Replay vs live testing

| Mode | Behaviour |
|---|---|
| Replay | Uses generated historical closeout dates, with the form pre-filled from generated observed data. Good for walking through the synthetic story. |
| Live test | Uses today's date and creates a recommendation for tomorrow. Defaults come from trailing synthetic history, because there's no generated outcome for today. |

Sidebar controls pick the closeout date: `Use today`, `Use latest generated day`, `Start 30-day replay`, `Advance one day`. The target date is always `closeout date + 1 day`.

## What the scorecard means

The scorecard is observed-only. It compares saved Dial In recommendations with the synthetic conservative gut-prep baseline. It doesn't use planted truth, so it isn't a true counterfactual, on purpose: the app shouldn't quietly prove itself with hidden data it wouldn't have in production.

It shows aggregate proxies (actual waste proxy, Dial In waste proxy, actual sellout rows, Dial In short proxy). It also separates followed and overridden days, captures override reasons, compares against both naive baselines (last week and trailing 4-week same weekday) on pinball loss and expected mis-prep cost, and reports calibration and per-category shadow/live model gates. None of it is presented as validated ROI.

## Pilot readiness

For a real pilot, the Setup tab records baseline and live phase windows and a setup checklist (open days, food revenue share, sellout frequency, waste handling, economics confirmed, POS export available). The How-it's-doing tab combines these, the model gates and the observed scorecard into a downloadable Markdown pilot report. It splits outcomes by phase and keeps observed facts, modelled estimates, assumptions and synthetic demo behaviour apart, and it never claims validated ROI. See `src/dialin/pilot_report.py` and `src/dialin/repository/pilot.py`.

## De-censoring probe

A category that always sells out never shows its real ceiling, so its upper quantile is extrapolated forever. When an account opts in (`accounts.decensor_probe_opt_in`), the engine preps a few units above the usual number on a small, deterministic share of low-risk days (no known event, no warm forecast) to see where demand really tops out. The extra is capped (bounded waste), shown in the Today view and recorded on the recommendation (`probe_active`, `probe_extra_units`).

The Fadri demo account opts in; the dummy account doesn't. The probe only switches on above the chronic-censoring threshold (trailing sellout rate above 0.38). The synthetic Fadri profile sells out on about 25 to 29% of days, so the probe stays off by design: it adds no waste unless a category is genuinely under-prepped. See PRD section 12 and `engine._probe_decision`.

## Known limits

- The default censoring correction is the demo-grade comparable-day method. The PRD's Tobit path exists (`src/dialin/censoring.py`, `censoring_method="tobit"`) but, like the demo method, stays advisory until it passes the section 6.4 ship gate on real held-out data.
- RLS isolation has database-backed tests (`tests/test_rls_isolation.py`, opt-in via `TEST_DATABASE_URL` and `TEST_APP_DATABASE_URL`) and has been spot-checked read-only on the hosted database. Run them against your target before loading real tenant data.
- The Streamlit auth setup is fine for a demo, not for production.
- Synthetic Fadri is fictionalised until real operating bands are provided.
- The de-censoring probe is bounded and opt-in. In the synthetic demo its "revealed demand" panel is measured against planted truth, which a real café doesn't have.
- The engine supports SKU-level prep: it never hardcodes `sweet`/`savory` and prices each category at its own service quantile (`tests/test_sku_level.py`). Only the demo data and UI still use two categories, so moving to per-SKU prep is a data and config change.
- The Service tab can show a modelled sellout and lost-sales estimate (`repository/intraday.estimate_lost_sales`). From an observed last-sale time and the demo traffic curve, it estimates full-day demand and units lost after a sellout. It's labelled illustrative and shows nothing without a real last-sale time.
- The pooled environment layer and cold-start prior have an estimator and an offline job (`src/dialin/shared_environment.py`, `scripts/train_shared_environment.py`). It reads only the anonymised `shared_layer_features` view, outputs parameters rather than raw rows, and refuses segments that are too sparse. The two-account demo is too sparse to fit, so the job says so and the engine uses the demo rules unless given a fitted layer via `build_recommendations(environment_layer=...)`.
