"""Fetch real Open-Meteo weather into the ``weather`` table for the demo accounts.

For each demo location it pulls the daily forecast (free, no API key) for the
next few days and backfills recent actuals from the ERA5 archive (PRD section
1.1/10.2). The app reads these rows through ``FrameWeatherProvider`` unchanged,
so a live recommendation for tomorrow runs on a real forecast. Run this **before**
``refresh_demo_data.py`` so the refreshed recommendations pick up the real
forecast. For *all active accounts* (not just the demo set), use
``scripts/scheduled_refresh.py``.

Uses ``DATABASE_URL`` (the low-privilege app role); every write is tenant-scoped.

Usage::

    uv run python scripts/fetch_weather.py
    uv run python scripts/fetch_weather.py --days 3 --actuals-days 14 --today 2026-06-20
"""

from __future__ import annotations

import argparse
from datetime import UTC, date, datetime

from dialin.config import load_settings, mask_database_url
from dialin.db import account_connection
from dialin.demo_freshness import DEMO_LOCATION_PAIRS
from dialin.weather import OpenMeteoWeatherProvider
from dialin.weather_sync import resolve_coordinates, store_location_weather


def fetch_and_store(
    database_url: str, *, today: date, forecast_days: int, actuals_days: int
) -> tuple[int, int]:
    """Upsert real forecasts and backfill actuals for the demo locations."""

    forecast_total = 0
    actual_total = 0
    for account_id, location_id in DEMO_LOCATION_PAIRS:
        with account_connection(database_url, account_id) as conn:
            coordinates = resolve_coordinates(conn, account_id, location_id)
            if coordinates is None:
                print(f"  {account_id}/{location_id}: no coordinates, skipped")
                continue
            latitude, longitude, timezone = coordinates
            provider = OpenMeteoWeatherProvider(latitude, longitude, timezone=timezone)
            stored, filled = store_location_weather(
                conn,
                provider,
                account_id,
                location_id,
                today=today,
                forecast_days=forecast_days,
                actuals_days=actuals_days,
            )
            forecast_total += stored
            actual_total += filled
            print(f"  {account_id}/{location_id}: {stored} forecast day(s), {filled} actual(s)")
    return forecast_total, actual_total


def main() -> None:
    """Parse options and fetch real forecasts and actuals into the weather table."""

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

    today = date.fromisoformat(args.today) if args.today else datetime.now(tz=UTC).date()
    settings = load_settings()
    print(f"fetching Open-Meteo weather into {mask_database_url(settings.database_url)}")
    forecasts, actuals = fetch_and_store(
        settings.database_url,
        today=today,
        forecast_days=args.days,
        actuals_days=args.actuals_days,
    )
    print(f"stored {forecasts} forecast row(s), backfilled {actuals} actual(s)")


if __name__ == "__main__":
    main()
