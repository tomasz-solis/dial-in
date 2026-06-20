# Dial In

Dial In is a synthetic Streamlit demo for the café fresh-prep workflow described in
`docs/PRD.md` and `docs/2026-05-31-synthetic-data-and-demo-design.md`.

The demo is intentionally honest: generated data can show the workflow, censoring story,
newsvendor decision layer, and replay mechanics. It does not prove real-world ROI.

## Production to do: replace non-real forecast inputs

Before Dial In is used as a daily operating tool for a real cafe, every non-real input that
can affect a recommendation must either be replaced with a real source or be shown in-app as
demo/advisory only. Current synthetic or placeholder inputs include:

- **Weather:** real forecasts are pulled from the Open-Meteo API (free, no API key) by
  `OpenMeteoWeatherProvider` in `src/dialin/weather.py`. Run `scripts/fetch_weather.py` to upsert
  the next few days' real forecasts (per location coordinates) into the `weather` table with
  `forecast_made_at`; the app reads them through `FrameWeatherProvider`, so a live recommendation
  for tomorrow runs on a real forecast. Forecast age, staleness, and the seasonal-normal fallback
  lower confidence as before. Forecast provenance is stored explicitly, and replacing a synthetic
  row clears its synthetic actual before the ERA5 reanalysis proxy is backfilled. The scheduled
  refresh fetches weather before rebuilding recommendations. Historical demo weather stays
  synthetic because the synthetic sales were generated from it.

  ```bash
  uv run python scripts/fetch_weather.py            # next 7 days, demo locations
  uv run python scripts/scheduled_refresh.py        # all discoverable active accounts
  ```
- **Usage and adherence:** demo closeouts, recommendation adherence, overrides, and health
  rates are synthetic until real operators use the app. They must not be presented as real
  adoption or business impact.
- **POS sales and traffic:** generated drinks/category sales are demo data. Production needs
  real POS import or owner-entered closeout data, with import failures and corrections audited.
- **Events, holidays, and tourism season:** demo events and seasonal lifts are generated or
  configured assumptions. Production needs confirmed calendars or owner-approved event inputs.
- **Economics:** category costs, prices, salvage, attach rate, and lost-margin assumptions are
  defaults until the owner confirms them.
- **Opening hours, closed days, and menu versions:** demo defaults drive comparability and
  regime-break logic. Production needs real hours, closure review, and menu-change markers.
- **Replay, savings, and scorecards:** demo outcomes estimate behavior on synthetic history.
  Real ROI requires held-out real data, baseline comparison, and model-gate reporting.

## Python

Use Python 3.12. The project pins `>=3.12,<3.13` because the Streamlit/data stack is more
reliable on 3.12 than on brand-new interpreter releases.

```bash
uv run python --version
```

## Local database

Docker is the intended local Postgres path.

```bash
docker compose up -d postgres
cp .env.example .env
uv run python scripts/migrate.py --target local
uv run python scripts/generate_synthetic_data.py --seed 20260531 --output data/generated
uv run python scripts/validate_realism.py data/generated
uv run python scripts/load_observed_data.py --observed-dir data/generated/observed --mode truncate-load
```

This environment did not have Docker installed when the scaffold was created, so the Docker
path still needs to be run on a machine with Docker Desktop available.

## Neon database

Set `MIGRATION_DATABASE_URL` to the Neon owner/admin connection and `DATABASE_URL` to the
low-privilege app role connection. If only `DATABASE_URL` exists during bootstrap, the
migration script uses it as the migration connection.

```bash
uv run python scripts/migrate.py --target neon
uv run python scripts/load_observed_data.py --observed-dir data/generated/observed --mode truncate-load
```

The app should run only with the low-privilege role in `DATABASE_URL`.

For an existing database that was migrated before the `schema_migrations` ledger existed,
baseline the migrations already present, then apply the new pending migration:

```bash
uv run python scripts/migrate.py --target neon --baseline-through 006_pos_imports.sql --plan
uv run python scripts/migrate.py --target neon --baseline-through 006_pos_imports.sql
```

To inspect without applying:

```bash
uv run python scripts/migrate.py --target neon --plan
```

To apply one migration explicitly:

```bash
uv run python scripts/migrate.py --target neon --only 007
```

## Streamlit app

Create `.streamlit/secrets.toml` from `.streamlit/secrets.example.toml` and replace the
password hashes and cookie key.

The app prefers `.env.local` when it exists, so local Streamlit runs use the
low-privilege `dialin_app` connection even when `.env` holds an owner/admin URL for
migrations.

```bash
uv run streamlit run app.py
```

The seeded demo accounts are:

- `acct_fadri`: Fadri (fictionalized), Cambrils, Tarragona
- `acct_dummy`: Station House Demo

## Keeping the demo fresh

The synthetic data has a finite timeline, so it would otherwise look stale a few days
after it is generated. The deployed app is kept current by the scheduled
`.github/workflows/refresh-demo-data.yml` workflow, which daily runs
`scripts/scheduled_refresh.py` (real Open-Meteo forecasts + ERA5 reanalysis proxies, followed by
the demo refresh). Fetching weather first means the regenerated
recommendations use the real forecast; the weather step is non-fatal so an API hiccup
falls back to seasonal-normal rather than stalling the refresh. Add a GitHub Actions
repository secret named `DATABASE_URL` that uses the low-privilege `dialin_app` role.

To pre-warm that work (so the first visitor does not wait) or to keep a deployed demo
current even when nobody has opened it, run the refresh script. It is idempotent — it only
appends missing days and re-generates recent recommendations, never overwriting real
entries.

```bash
uv run python scripts/refresh_demo_data.py
uv run python scripts/refresh_demo_data.py --today 2026-06-20   # treat a chosen date as today
```

It uses `DATABASE_URL` (the low-privilege `dialin_app` role is sufficient; row-level
security is satisfied because each write is scoped to its tenant). Stop the running app
before invoking it if `uv` needs to re-sync the environment, since a running process locks
the virtualenv on Windows. For a hosted demo with no built-in scheduler (e.g. Streamlit
Community Cloud), run it on a schedule from elsewhere — Windows Task Scheduler, macOS
`launchd`/cron, or a daily GitHub Action with `DATABASE_URL` set as a secret.

For emergency self-healing during a manual demo, set `DIALIN_DEMO_REFRESH_ON_LOAD=true`
in Streamlit secrets or the local environment. Leave it unset in production so visitors do
not pay the refresh cost during app startup.

## Checks

```bash
uv run ruff check
uv run mypy
uv run pytest
uv run python scripts/validate_realism.py data/generated
```

Database-backed RLS tests (`tests/test_rls_isolation.py`) prove that one account cannot read
or write another account's rows through the low-privilege app role. They are skipped unless
both `TEST_DATABASE_URL` (admin/owner connection, used to migrate and seed) and
`TEST_APP_DATABASE_URL` (the `dialin_app` role connection) are set:

```bash
TEST_DATABASE_URL=postgresql://owner:...@host/dialin \
TEST_APP_DATABASE_URL=postgresql://dialin_app:...@host/dialin \
  uv run pytest tests/test_rls_isolation.py
```

CI runs these automatically: the `rls` job in `.github/workflows/ci.yml` spins up a
Postgres service, creates the low-privilege role with `scripts/ci_create_app_role.py`, and
runs the isolation tests, so tenant isolation is an enforced gate rather than a local-only one.

The live weather provider has a network-gated test (it actually calls Open-Meteo), skipped by
default so the suite stays offline-deterministic:

```bash
DIALIN_WEATHER_LIVE_TEST=1 uv run pytest tests/test_weather_openmeteo.py
```

## Implementation status & what's next

`docs/PRD.md` §23 carries the authoritative status. In short: the decision engine, RLS (tested
in CI), real Open-Meteo weather, the real-data Tobit censoring path, honest measurement and
model gates, attribution and pilot reporting, the pooled environment-layer estimator, SKU
readiness, and a modelled intraday sellout estimate are all built. Still synthetic/advisory:
sales, traffic, events, economics, hours, and usage/adherence (until a real café uses the app).
Candidate next steps: real event/holiday feeds, POS API import, backups and monitoring before a
real-data pilot, managed auth before multi-tenant selling, an event-driven weather re-fetch, and a
Tobit-vs-baseline A/B on real held-out data.

## Before selling beyond a controlled paid pilot

The codebase is ready to support an honest, concierge-run pilot; it is not yet a self-serve
production SaaS. The next work is ordered by risk, not novelty. `docs/PRD.md` §23 contains the
full acceptance criteria.

1. **Operate safely:** managed user lifecycle, backup retention plus a successful restore drill,
   alerting/runbooks, access audit, secret rotation, and hard separation of real tenants from demo
   refresh/truth paths.
2. **Prove speed in hosting:** instrument the full request path and hold warm p95 Today load under
   3 seconds, closeout-to-recommendation under 5 seconds, and cached view changes under 1 second
   for at least seven days. A local health response is not a product latency measurement.
3. **Prove the decision on real held-out data:** run shadow mode, freeze recommendation snapshots,
   compare Tobit and comparable-day against both naive baselines on identical dates, and keep every
   category advisory until its model gate clears.
4. **Prove the workflow and business:** median closeout under 30 seconds, completion at least 90%
   of open days, transparent override/adherence reporting, value uncertainty reported, and an
   explicit paid-continuation decision from the owner at the end of the pilot.
5. **Make onboarding repeatable:** operator-safe location/coordinates/hours/economics setup,
   reusable and idempotent POS mappings, import freshness/reconciliation, then a configured
   category/SKU closeout UI instead of hard-coded sweet/savory inputs.

Do not expand into staffing, ingredients, inventory ordering, or benchmarking until a real café
clears both the model gate and the paid-continuation gate.
