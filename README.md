# Dial In

Dial In is a fresh-prep decision product for cafés, with a synthetic Streamlit demo and a
controlled real-data pilot path described in `docs/PRD.md` and
`docs/2026-05-31-synthetic-data-and-demo-design.md`.

The demo is intentionally honest: generated data can show the workflow, censoring story,
newsvendor decision layer, and replay mechanics. It does not prove real-world ROI.

## Product status

Dial In is ready to sell as a tightly managed, advisory real-data pilot. It is not yet a
self-serve production SaaS product. A paid pilot should use one real location, confirmed
economics, frozen recommendations, clean daily closeouts, and the Performance page's owner
summary plus advanced evidence. Synthetic results are demonstration evidence only.

Before broader or multi-tenant sales, complete the operational gates in PRD section 23: a tested
database restore, monitored refresh/migration/weather failures, managed user lifecycle, real-data
held-out model proof, repeatable onboarding/POS reconciliation, and an explicit pay-again decision.

## Production to do: replace non-real forecast inputs

Before Dial In is used as a daily operating tool for a real cafe, every non-real input that
can affect a recommendation must either be replaced with a real source or be shown in-app as
demo/advisory only. Current synthetic or placeholder inputs include:

- **Weather:** done — this is the one input that is now externally sourced. `scripts/fetch_weather.py`
  pulls the daily forecast from Open-Meteo (free, no API key) and an outcome proxy afterwards from the ERA5
  archive, and writes both to the `weather` table tagged with their source. The app reads them back
  the same way it always did, so tomorrow's recommendation runs on a real forecast; a stale or
  missing forecast still falls back to seasonal-normal and lowers confidence. Only the *historical*
  demo weather stays synthetic, because the synthetic sales were generated from it. ERA5 is
  reanalysis, not a station reading, so it is labelled as an outcome proxy rather than measured truth.

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
`scripts/scheduled_refresh.py` (real Open-Meteo forecasts and ERA5 outcome proxies first, then the demo
refresh). Fetching weather first means the regenerated
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
