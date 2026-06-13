# Dial In

Dial In is a synthetic Streamlit demo for the café fresh-prep workflow described in
`docs/PRD.md` and `docs/2026-05-31-synthetic-data-and-demo-design.md`.

The demo is intentionally honest: generated data can show the workflow, censoring story,
newsvendor decision layer, and replay mechanics. It does not prove real-world ROI.

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
after it is generated. The app self-heals on load: `ensure_demo_data_fresh` extends the
synthetic history up to the current date and regenerates recent recommendations whenever
a session starts, so a shared link is current whenever someone opens it.

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

## Checks

```bash
uv run ruff check
uv run mypy
uv run pytest
```

Database-backed RLS tests require a reachable Postgres URL and are skipped when no test
database is configured.
