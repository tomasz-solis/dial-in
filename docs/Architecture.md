# Dial In Architecture and Methodology

This document explains how the current synthetic demo works. It is the engineering view of
the app, not a replacement for the PRD. Dial In is currently a learning project and
Fadri-ready decision-support demo, not a product being prepared for sale.

## What The Demo Does

Dial In answers one daily question for a cafe:

> How much fresh food should we prepare for tomorrow?

The demo uses generated synthetic data. That matters. It can show the workflow, data shape,
censoring problem, and decision logic. It cannot prove that the app saves money in a real
cafe. Real learning needs the future Fadri data path.

The scaffold currently includes these paths. Local and hosted RLS still need to be proven with
DB-backed checks before any real tenant data is loaded:

- Login-gated Streamlit UI.
- Two synthetic demo tenants: `acct_fadri` and `acct_dummy`.
- A planned real-data path for Fadri Café using the same account-scoped workflow.
- Account-scoped Postgres reads and writes through repository helpers.
- Row-level security policies using `app.current_account_id`.
- Synthetic observed data loading into Postgres.
- Planted truth stored only on disk and never loaded into Postgres.
- End-of-day closeout entry.
- Immediate next-day recommendation generation.
- Replay controls for synthetic demo history.

## Main Components

### Streamlit app

Entry point: `app.py`

The app handles:

- Login through `streamlit-authenticator`.
- Mapping a username to an internal `account_id`.
- Selecting the current closeout date.
- Showing the recommendation for `closeout_date + 1`.
- Collecting v1 manual closeout input:
  - drinks sold
  - sweet sold
  - sweet prepared
  - savory sold
  - savory prepared
- Persisting closeout rows.
- Running and storing recommendations.
- Showing an observed-only synthetic scorecard.

The login username is not the account id. In the current demo, Streamlit secrets bind each
username to one `account_id`; `account_members` is available for a later DB-owned mapping path
but should not become a competing source of truth. For example:

- username `demo` maps to `acct_fadri`
- username `dummy` maps to `acct_dummy`

### Database

Migrations live in `migrations/`.

The schema is plain Postgres. It does not use Neon-specific, Supabase-specific, or hosted
provider-specific APIs.

Important tables:

- `accounts`
- `account_members`
- `locations`
- `daily_metrics`
- `daily_category_metrics`
- `weather`
- `events`
- `category_economics`
- `recommendations`
- `data_corrections`

Every operational row is scoped by `account_id` and `location_id`.

### Tenant isolation

Tenant isolation has two layers.

Application layer:

- Repository functions always filter by `account_id`.
- The app gets `account_id` from login/session state.
- The app does not trust a browser-supplied account id.

Database layer:

- RLS is enabled on tenant tables.
- Each account-scoped DB transaction runs:

```sql
SELECT set_config('app.current_account_id', '<account_id>', true);
```

- RLS policies compare row `account_id` to that setting.
- If the app forgets an account filter, Postgres should still block cross-account reads.

### Synthetic generator

Generator code: `src/dialin/generator.py`

The generator creates two outputs:

- `data/generated/observed/`
- `data/generated/truth/`

Observed files are safe to load into Postgres. Truth files are not.

Observed files include:

- accounts
- locations
- daily metrics
- daily category metrics
- weather
- events
- category economics

Truth files include planted demand:

- true drinks
- true category demand
- lost units
- waste units

The app must never read truth files. That is an honesty boundary, not just a convenience.

## Data Flow

The normal local flow is:

1. Run migrations against Postgres.
2. Generate synthetic data.
3. Validate synthetic data realism and truth separation.
4. Load observed data into Postgres.
5. Start Streamlit.
6. Login as a demo user.
7. Submit a closeout day.
8. Generate tomorrow's recommendation.
9. Store the recommendation in Postgres.
10. Show the stored result in the UI.

The recommendation is persisted. Reopening the app should show the stored recommendation for
the selected closeout date's next day. It should not silently recompute a different result.

## Why Censoring Matters

The central problem is that sales are not always demand.

If a cafe prepared 40 pastries and sold 40, demand might have been 40. It also might have
been 55. The observed sales number is capped by preparation. That is censored demand.

A naive forecast trained on raw sales will learn the cafe's old preparation ceiling. It will
look accurate on sellout days while repeating the same under-prep mistake.

The demo uses a light censoring correction:

- If a category did not sell out, observed sold is treated as demand.
- If a category sold out, estimated demand is lifted using comparable non-sellout days.
- Comparable days use same weekday history and scale by drinks sold.
- If there are too few comparable days, fallback demand is `prepared * 1.15`.

This is the current demo method. The companion design describes a richer demo target with
weather buckets, and the PRD describes the real-data censoring-aware method. Those are separate
levels on purpose: current demo, intended demo, and real-data path. The current method is enough
to demonstrate the behavior, not enough to claim production validation.

## Forecast Method

The v1 engine lives in `src/dialin/engine.py`.

For a target date, it calculates:

### 1. Traffic forecast

Traffic is proxied by drinks sold.

The demo forecast starts with a trailing same-weekday mean:

```text
base traffic = average drinks sold on recent same weekdays
```

Then it applies:

```text
traffic forecast = base traffic * weather multiplier * event multiplier
```

Weather multiplier:

- warm weather can lift traffic
- rain can suppress traffic
- bounds prevent extreme swings

Event multiplier:

- each event has an `impact_score`
- event multiplier is the product of `1 + impact_score`

### 2. De-censored attach rate

Attach rate means category demand per drink.

```text
attach rate = estimated category demand / drinks sold
```

The key detail is that attach rate uses estimated demand, not raw sold, so sellout days do
not automatically bias the model downward.

### 3. Demand mean

For each category:

```text
demand mean = traffic forecast * attach rate
```

The current categories are:

- `sweet`
- `savory`

### 4. Demand distribution

The app needs a distribution, not just a point forecast, because the prep decision depends on
risk.

The demo uses a Negative Binomial distribution because pastry demand is count data and is
usually more variable than a Poisson model allows.

The engine estimates dispersion from recent corrected demand. If history is thin, it falls
back to a conservative default.

### 5. Newsvendor decision

The recommendation is not the mean. It is the quantity that balances under-prep and over-prep
cost.

The service quantile is:

```text
q* = Cu / (Cu + Co)
```

Where:

```text
Cu = under-prep cost
Co = over-prep cost
```

In plain terms:

- running out loses pastry margin
- running out may also lose an attached drink
- over-prep loses COGS after salvage

Example:

```text
Cu = lost pastry margin + attached drink loss
Co = unit COGS after salvage
q* = Cu / (Cu + Co)
```

If running out is much more expensive than waste, `q*` is above 0.5. That means the app
recommends a higher percentile than the median.

The app stores `service_quantile` in `category_economics` and copies it into every
recommendation for auditability.

### 6. Output

For each category, the engine stores:

- recommended prep
- p50 demand
- lower demand bound
- upper demand bound
- service quantile
- confidence
- risk flag
- top drivers
- model version
- input snapshot hash
- config snapshot hash
- generated timestamp

## Confidence and Risk

Confidence is based on:

- history depth
- recent censoring rate
- missing weather

High sellout rates reduce confidence because the upper demand tail is not well observed.

Risk flags are simple owner-facing labels:

- `Normal`
- `High demand possible`
- `Stockout learning needed`

The purpose is not to sound precise. The purpose is to tell the operator when the model is
leaning on weaker evidence.

## Replay Versus Live Testing

The app has two useful modes.

Replay:

- uses generated historical closeout dates
- form values are prefilled from generated observed data
- useful for walking through the synthetic story

Live test:

- uses today's real date
- creates a recommendation for tomorrow
- defaults come from trailing synthetic history because no generated outcome exists for today

The sidebar controls choose the closeout date:

- `Use today`
- `Use latest generated day`
- `Start 30-day replay`
- `Advance one day`

The target recommendation date is always:

```text
target date = closeout date + 1 day
```

## What The Scorecard Means

The scorecard is observed-only. It compares stored Dial In recommendations against the
synthetic conservative gut-prep baseline.

It does not use planted truth, so it is not a true counterfactual. That is intentional. The app
should not quietly prove itself using hidden data it would not have in production.

The current scorecard can show aggregate proxies:

- actual waste proxy
- Dial In waste proxy
- actual sellout rows
- Dial In short proxy

This is a demo comparison, not validated ROI.

Planned attribution work will add per-day wins/losses, adherence splits, override reasons, and
baseline metrics before the scorecard is used for any real pilot claim.

## Known Limits

- The censoring correction is demo-grade.
- Docker/RLS should be verified locally before touching Neon.
- The current Streamlit auth setup is good enough for a demo, not production auth.
- Synthetic Fadri is fictionalized until real operating bands are provided.
- There is no POS import yet.
- There is no SKU-level recommendation yet.
