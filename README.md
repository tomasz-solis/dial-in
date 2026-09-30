# Dial In

A fresh-prep decision tool for cafés: how much to prep tomorrow. It has a synthetic Streamlit demo and a controlled real-data pilot path, both described in `docs/PRD.md` and `docs/2026-05-31-synthetic-data-and-demo-design.md`.

The demo is honest about what it is. Generated data shows the workflow, the censoring story, the newsvendor decision layer and the replay mechanics. It doesn't prove real-world ROI.

## Status

Ready to sell as a tightly managed, advisory pilot on real data. Not yet a self-serve SaaS product. A paid pilot should use one real location, confirmed economics, frozen recommendations, clean daily closeouts, and the Performance page's owner summary plus advanced evidence. Synthetic results are for demonstration only.

Before wider or multi-tenant sales, pass the operational gates in PRD section 23: a tested database restore; monitoring for refresh, migration and weather failures; managed user lifecycle; held-out model proof on real data; repeatable onboarding and POS reconciliation; and an explicit "would pay again" decision.

## To do before production: replace non-real forecast inputs

Before Dial In runs a real café's day, every non-real input that can affect a recommendation must be replaced with a real source or shown in the app as demo or advisory only.

| Input | Status |
|---|---|
| Weather | Done. The only input sourced externally today. `scripts/fetch_weather.py` pulls the daily forecast from Open-Meteo (free, no API key) and, afterwards, an outcome proxy from the ERA5 archive, and writes both to the `weather` table tagged with their source. Tomorrow's recommendation uses a real forecast; a stale or missing forecast falls back to seasonal normal and lowers confidence. Only the historical demo weather stays synthetic, because the synthetic sales were generated from it. ERA5 is reanalysis, not a station reading, so it is labelled an outcome proxy, not measured truth. |
| Usage and adherence | Demo closeouts, recommendation adherence, overrides and health rates are synthetic until real operators use the app. They must not be shown as real adoption or business impact. |
| POS sales and traffic | Generated drink and category sales are demo data. Production needs real POS import or owner-entered closeouts, with failed imports and corrections audited. |
| Events, holidays, tourism season | Demo events and seasonal lifts are generated or configured assumptions. Production needs confirmed calendars or owner-approved events. |
| Economics | Category costs, prices, salvage, attach rate and lost-margin assumptions are defaults until the owner confirms them. |
| Opening hours, closed days, menu versions | Demo defaults drive comparability and regime-break logic. Production needs real hours, closure review and menu-change markers. |
| Replay, savings, scorecards | Demo outcomes estimate behaviour on synthetic history. Real ROI needs held-out real data, a baseline comparison and model-gate reporting. |

Weather commands:

```bash
uv run python scripts/fetch_weather.py            # next 7 days, demo locations
uv run python scripts/scheduled_refresh.py        # all discoverable active accounts
```

## Python

Python 3.12. The project pins `>=3.12,<3.13` because the Streamlit and data stack is more reliable on 3.12 than on brand-new releases.

```bash
uv run python --version
```

## Local database

Local Postgres runs in Docker.

```bash
docker compose up -d postgres
cp .env.example .env
uv run python scripts/migrate.py --target local
uv run python scripts/generate_synthetic_data.py --seed 20260531 --output data/generated
uv run python scripts/validate_realism.py data/generated
uv run python scripts/load_observed_data.py --observed-dir data/generated/observed --mode truncate-load
```

Docker wasn't installed where the scaffold was built, so the Docker path still needs a run on a machine with Docker Desktop.

## Neon database

Set `MIGRATION_DATABASE_URL` to the Neon owner/admin connection and `DATABASE_URL` to the low-privilege app role. If only `DATABASE_URL` exists during bootstrap, the migration script uses it for migrations too.

```bash
uv run python scripts/migrate.py --target neon
uv run python scripts/load_observed_data.py --observed-dir data/generated/observed --mode truncate-load
```

The app should only run with the low-privilege role in `DATABASE_URL`.

A database migrated before the `schema_migrations` ledger existed needs a baseline of the migrations already applied, then the new pending ones:

```bash
uv run python scripts/migrate.py --target neon --baseline-through 006_pos_imports.sql --plan
uv run python scripts/migrate.py --target neon --baseline-through 006_pos_imports.sql
```

Preview without applying:

```bash
uv run python scripts/migrate.py --target neon --plan
```

Apply one migration:

```bash
uv run python scripts/migrate.py --target neon --only 007
```

## Streamlit app

Create `.streamlit/secrets.toml` from `.streamlit/secrets.example.toml` and replace the password hashes and cookie key.

The app prefers `.env.local` when it exists, so local runs use the low-privilege `dialin_app` connection even when `.env` holds an owner/admin URL for migrations.

```bash
uv run streamlit run app.py
```

Seeded demo accounts:

- `acct_fadri`: Fadri (fictionalised), Cambrils, Tarragona
- `acct_dummy`: Station House Demo

## Keeping the demo fresh

The synthetic data has a fixed timeline, so it would look stale a few days after generation. The `.github/workflows/refresh-demo-data.yml` workflow keeps the deployed app current: it runs `scripts/scheduled_refresh.py` daily, fetching real Open-Meteo forecasts and ERA5 outcome proxies first and then refreshing the demo. Weather goes first so the new recommendations use the real forecast. The weather step can fail without stopping the refresh; it falls back to seasonal normal. Add a GitHub Actions secret named `DATABASE_URL` that uses the low-privilege `dialin_app` role.

To pre-warm the demo so the first visitor doesn't wait, or to keep it current when nobody opens it, run the refresh script. It is idempotent: it only adds missing days and regenerates recent recommendations, and never overwrites real entries.

```bash
uv run python scripts/refresh_demo_data.py
uv run python scripts/refresh_demo_data.py --today 2026-06-20   # treat a chosen date as today
```

It uses `DATABASE_URL`. The low-privilege `dialin_app` role is enough, because every write is scoped to its tenant and row-level security allows it. Stop the running app first if `uv` needs to re-sync, since on Windows a running process locks the virtualenv. For a host with no scheduler (such as Streamlit Community Cloud), schedule it elsewhere: Windows Task Scheduler, macOS `launchd` or cron, or a daily GitHub Action with `DATABASE_URL` as a secret.

For emergency self-healing during a live demo, set `DIALIN_DEMO_REFRESH_ON_LOAD=true` in Streamlit secrets or the local environment. Leave it unset in production so visitors don't pay the refresh cost at startup.

## Checks

```bash
uv run ruff check
uv run mypy
uv run pytest
uv run python scripts/validate_realism.py data/generated
```

The database-backed RLS tests (`tests/test_rls_isolation.py`) prove that one account can't read or write another account's rows through the low-privilege role. They are skipped unless both `TEST_DATABASE_URL` (admin/owner connection, used to migrate and seed) and `TEST_APP_DATABASE_URL` (the `dialin_app` role) are set:

```bash
TEST_DATABASE_URL=postgresql://owner:...@host/dialin \
TEST_APP_DATABASE_URL=postgresql://dialin_app:...@host/dialin \
  uv run pytest tests/test_rls_isolation.py
```

CI runs them automatically. The `rls` job in `.github/workflows/ci.yml` starts a Postgres service, creates the low-privilege role with `scripts/ci_create_app_role.py` and runs the isolation tests, so tenant isolation is an enforced gate.

The live weather test calls Open-Meteo, so it is skipped by default to keep the suite offline and deterministic:

```bash
DIALIN_WEATHER_LIVE_TEST=1 uv run pytest tests/test_weather_openmeteo.py
```
