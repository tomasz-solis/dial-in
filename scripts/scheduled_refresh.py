"""One scheduled maintenance job for a hosted Dial In demo (Neon + Streamlit).

Run this on a schedule (GitHub Actions, cron, Windows Task Scheduler, ...). It:

1. **Fetches real Open-Meteo weather** (forecasts + recent actuals) for every
   active account that has location coordinates.
2. **Refreshes synthetic demo data** for the demo accounts — including the dummy
   account — up to today.

Weather is fetched first on purpose, so the refresh regenerates recommendations
from the real forecast instead of stale/synthetic weather.

Connections:

* ``DATABASE_URL`` (low-privilege app role) — used for every tenant-scoped read
  and write, so the whole job is RLS-safe. Sufficient on its own to cover the
  built-in demo accounts.
* ``MIGRATION_DATABASE_URL`` (admin/owner) — *optional*. Used only to **discover**
  accounts beyond the demo set (a cross-tenant read of ``accounts``). If it is
  unset, or cannot read across tenants, the job still covers the demo accounts
  and prints that it did so.

Both steps are wrapped so one failure (e.g. the weather API being down) does not
abort the rest of the run.

Usage::

    uv run python scripts/scheduled_refresh.py
    uv run python scripts/scheduled_refresh.py --days 3 --actuals-days 14 --today 2026-06-20
"""

from __future__ import annotations

import argparse
import os
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import psycopg

from dialin.config import load_settings, mask_database_url
from dialin.db import account_connection, admin_connection, fetch_all
from dialin.demo_freshness import (
    DEMO_LOCATION_PAIRS,
    ensure_demo_data_fresh,
    latest_metric_date,
)
from dialin.weather import OpenMeteoWeatherProvider
from dialin.weather_sync import resolve_coordinates, store_location_weather


def demo_account_ids() -> set[str]:
    """Return the built-in demo account ids."""

    return {account_id for account_id, _ in DEMO_LOCATION_PAIRS}


def active_account_ids(demo_accounts: set[str], admin_url: str | None) -> tuple[list[str], bool]:
    """Return (sorted account ids to service, whether discovery found extra ones).

    Always includes the demo accounts; if an admin connection is available and can
    read ``accounts`` across tenants, any additional accounts are folded in.
    """

    discovered = _discover_account_ids(admin_url) if admin_url else []
    extra = sorted(set(discovered) - demo_accounts)
    return sorted(demo_accounts | set(discovered)), bool(extra)


def _discover_account_ids(admin_url: str) -> list[str]:
    """Best-effort cross-tenant read of account ids; empty on any failure."""

    try:
        with admin_connection(admin_url) as conn:
            rows = fetch_all(conn, "SELECT account_id FROM accounts ORDER BY account_id")
    except psycopg.Error as error:
        print(f"  account discovery failed ({error}); covering demo accounts only")
        return []
    return [str(row["account_id"]) for row in rows]


def refresh_demo_data(database_url: str, today: date) -> int:
    """Extend demo history to today for the demo accounts; return recommendation rows."""

    total = 0
    for account_id, location_id in DEMO_LOCATION_PAIRS:
        if latest_metric_date(database_url, account_id, location_id) is None:
            print(
                f"  {account_id}/{location_id}: no seed data — run "
                "scripts/load_observed_data.py first; skipping"
            )
            continue
        result = ensure_demo_data_fresh(
            database_url=database_url,
            account_id=account_id,
            location_id=location_id,
            today=today,
        )
        total += result.recommendation_rows
        print(
            f"  {account_id}/{location_id}: +{len(result.observed_dates)} observed day(s), "
            f"{result.recommendation_rows} recommendation rows"
        )
    return total


def fetch_weather_for_accounts(
    database_url: str,
    account_ids: list[str],
    *,
    today: date | None,
    forecast_days: int,
    actuals_days: int,
) -> tuple[int, int]:
    """Fetch real weather for every located site of each account; return (forecasts, actuals)."""

    forecast_total = 0
    actual_total = 0
    for account_id in account_ids:
        try:
            with account_connection(database_url, account_id) as conn:
                locations = fetch_all(
                    conn,
                    "SELECT location_id FROM locations WHERE account_id = %s ORDER BY location_id",
                    (account_id,),
                )
                for location in locations:
                    location_id = str(location["location_id"])
                    coordinates = resolve_coordinates(conn, account_id, location_id)
                    if coordinates is None:
                        continue
                    latitude, longitude, timezone = coordinates
                    location_today = today or _today_in_timezone(timezone)
                    provider = OpenMeteoWeatherProvider(latitude, longitude, timezone=timezone)
                    stored, filled = store_location_weather(
                        conn,
                        provider,
                        account_id,
                        location_id,
                        today=location_today,
                        forecast_days=forecast_days,
                        actuals_days=actuals_days,
                    )
                    forecast_total += stored
                    actual_total += filled
                    print(
                        f"  {account_id}/{location_id}: {stored} forecast day(s), "
                        f"{filled} actual(s)"
                    )
        except psycopg.Error as error:
            print(f"  {account_id}: weather skipped ({error})")
    return forecast_total, actual_total


def _today_in_timezone(timezone: str) -> date:
    """Return the location's current business date, falling back to UTC."""

    try:
        return datetime.now(tz=ZoneInfo(timezone)).date()
    except (ZoneInfoNotFoundError, ValueError):
        return datetime.now(tz=UTC).date()


def main() -> None:
    """Refresh demo data and fetch real weather for all active accounts."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=7, help="Forecast horizon in days.")
    parser.add_argument(
        "--actuals-days",
        type=int,
        default=60,
        help="How far back to scan for forecast rows still missing an observed actual.",
    )
    parser.add_argument("--today", help="Treat this YYYY-MM-DD as today.")
    args = parser.parse_args()

    today_override = date.fromisoformat(args.today) if args.today else None
    refresh_today = today_override or datetime.now(tz=UTC).date()
    settings = load_settings()
    admin_url = os.environ.get("MIGRATION_DATABASE_URL")
    print(f"scheduled refresh on {mask_database_url(settings.database_url)} up to {refresh_today}")

    # Fetch weather FIRST so the demo refresh regenerates recommendations from the
    # real forecast (the refresh only inserts synthetic context weather when none
    # exists, so a real forecast written here is preserved).
    account_ids, found_extra = active_account_ids(demo_account_ids(), admin_url)
    scope = "all active accounts" if found_extra else "demo accounts"
    print(f"fetching weather for {scope} ({len(account_ids)})...")
    forecasts, actuals = fetch_weather_for_accounts(
        settings.database_url,
        account_ids,
        today=today_override,
        forecast_days=args.days,
        actuals_days=args.actuals_days,
    )

    print("refreshing demo data...")
    recommendation_rows = refresh_demo_data(settings.database_url, refresh_today)

    print(
        f"done — {forecasts} forecast row(s), {actuals} actual(s) backfilled, "
        f"{recommendation_rows} recommendation rows"
    )


if __name__ == "__main__":
    main()
