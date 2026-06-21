"""Persist real Open-Meteo weather into the ``weather`` table (tenant-scoped).

Shared by ``scripts/fetch_weather.py`` and ``scripts/scheduled_refresh.py`` so the
DB-writing logic lives in the package (importable, testable) and the scripts stay
thin CLIs. Every write runs on an account-scoped connection, so RLS holds with the
low-privilege app role.

ERA5 reanalysis outcome proxies are only backfilled onto rows the forecast wrote
(``forecast_source = 'open_meteo'``), so the generator's synthetic history is left
alone.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from psycopg import Connection

from dialin.db import fetch_all, fetch_one
from dialin.generator import default_cafes
from dialin.weather import OpenMeteoWeatherProvider

Coordinates = tuple[float, float, str]

_UPSERT_FORECAST = """
INSERT INTO weather
    (account_id, location_id, date, temp_forecast, rain_forecast, wind,
     condition, forecast_source, forecast_made_at)
VALUES
    (%(account_id)s, %(location_id)s, %(date)s, %(temp_forecast)s,
     %(rain_forecast)s, %(wind)s, %(condition)s, 'open_meteo', %(forecast_made_at)s)
ON CONFLICT (account_id, location_id, date) DO UPDATE SET
    temp_forecast = EXCLUDED.temp_forecast,
    rain_forecast = EXCLUDED.rain_forecast,
    wind = EXCLUDED.wind,
    condition = EXCLUDED.condition,
    forecast_source = EXCLUDED.forecast_source,
    forecast_made_at = EXCLUDED.forecast_made_at,
    temp_actual = NULL,
    rain_actual = NULL,
    actual_observed_at = NULL
"""

_UPDATE_ACTUAL = """
UPDATE weather
SET temp_actual = %(temp_actual)s,
    rain_actual = %(rain_actual)s,
    actual_observed_at = now()
WHERE account_id = %(account_id)s
  AND location_id = %(location_id)s
  AND date = %(date)s
  AND forecast_source = 'open_meteo'
  AND temp_actual IS NULL
"""


def default_coordinates(account_id: str, location_id: str) -> Coordinates | None:
    """Return the generator's seeded coordinates for a known demo location."""

    for cafe in default_cafes():
        if cafe.account_id == account_id and cafe.location_id == location_id:
            return cafe.latitude, cafe.longitude, cafe.timezone
    return None


def resolve_coordinates(
    conn: Connection[Any], account_id: str, location_id: str
) -> Coordinates | None:
    """Return (lat, lon, timezone) from the stored location, or seeded demo defaults."""

    row = fetch_one(
        conn,
        """
        SELECT latitude, longitude, timezone
        FROM locations
        WHERE account_id = %s AND location_id = %s
        """,
        (account_id, location_id),
    )
    if row and row.get("latitude") is not None and row.get("longitude") is not None:
        return float(row["latitude"]), float(row["longitude"]), str(row["timezone"] or "auto")
    return default_coordinates(account_id, location_id)


def store_forecasts(
    conn: Connection[Any],
    provider: OpenMeteoWeatherProvider,
    account_id: str,
    location_id: str,
    start: date,
    end: date,
) -> int:
    """Upsert real forecast rows for an inclusive date range; return rows written."""

    try:
        forecasts = provider.daily_forecasts(start, end)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        print(f"  {account_id}/{location_id}: forecast skipped ({error})")
        return 0
    stored = 0
    for day, forecast in sorted(forecasts.items()):
        if forecast.missing or forecast.wind is None:
            continue
        conn.execute(
            _UPSERT_FORECAST,
            {
                "account_id": account_id,
                "location_id": location_id,
                "date": day,
                "temp_forecast": round(forecast.temp_forecast, 2),
                "rain_forecast": round(forecast.rain_forecast, 2),
                "wind": round(forecast.wind, 2),
                "condition": forecast.condition,
                "forecast_made_at": forecast.forecast_made_at,
            },
        )
        stored += 1
    return stored


def missing_actual_dates(
    conn: Connection[Any],
    account_id: str,
    location_id: str,
    *,
    today: date,
    max_lookback_days: int,
) -> list[date]:
    """Return past real-forecast dates that still lack a reanalysis outcome.

    These are exactly the rows a forecast wrote (synthetic demo weather always
    has an actual), so this drives a no-holes backfill rather than a fixed window.
    """

    lower_bound = today - timedelta(days=max(max_lookback_days, 1))
    rows = fetch_all(
        conn,
        """
        SELECT date
        FROM weather
        WHERE account_id = %s AND location_id = %s
          AND temp_actual IS NULL
          AND forecast_source = 'open_meteo'
          AND date < %s AND date >= %s
        ORDER BY date
        """,
        (account_id, location_id, today, lower_bound),
    )
    return [row["date"] for row in rows]


def backfill_actuals(
    conn: Connection[Any],
    provider: OpenMeteoWeatherProvider,
    account_id: str,
    location_id: str,
    *,
    today: date,
    max_lookback_days: int,
) -> int:
    """Fill reanalysis outcomes for every past forecast row still missing them.

    Queries which dates are missing (within ``max_lookback_days``) and fetches the
    ERA5 archive for exactly that span, so a gap of any size is closed and nothing
    is left with a hole. Dates too recent for the archive stay null and are
    retried on the next run.
    """

    missing = missing_actual_dates(
        conn, account_id, location_id, today=today, max_lookback_days=max_lookback_days
    )
    if not missing:
        return 0
    try:
        actuals = provider.daily_actuals(missing[0], missing[-1])
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        print(f"  {account_id}/{location_id}: actuals skipped ({error})")
        return 0
    missing_set = set(missing)
    filled = 0
    for day, (temp_actual, rain_actual) in sorted(actuals.items()):
        if day not in missing_set or (temp_actual is None and rain_actual is None):
            continue
        cursor = conn.execute(
            _UPDATE_ACTUAL,
            {
                "account_id": account_id,
                "location_id": location_id,
                "date": day,
                "temp_actual": None if temp_actual is None else round(temp_actual, 2),
                "rain_actual": None if rain_actual is None else round(rain_actual, 2),
            },
        )
        filled += int(cursor.rowcount or 0)
    return filled


def store_location_weather(
    conn: Connection[Any],
    provider: OpenMeteoWeatherProvider,
    account_id: str,
    location_id: str,
    *,
    today: date,
    forecast_days: int,
    actuals_days: int,
) -> tuple[int, int]:
    """Upsert forecasts and backfill missing actuals for one location.

    Returns (forecast rows written, actual rows backfilled). ``actuals_days`` is
    how far back to look for forecast rows still missing a reanalysis outcome.
    """

    forecast_end = today + timedelta(days=max(forecast_days, 1) - 1)
    stored = store_forecasts(conn, provider, account_id, location_id, today, forecast_end)
    filled = backfill_actuals(
        conn, provider, account_id, location_id, today=today, max_lookback_days=actuals_days
    )
    return stored, filled
