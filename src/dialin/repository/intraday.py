"""Synthetic intraday service-pressure shape for the Service tab."""

from __future__ import annotations

import math
from datetime import date, datetime, time
from typing import Any

import pandas as pd

from dialin.db import account_connection, fetch_all, fetch_one
from dialin.repository._common import _as_date
from dialin.repository.locations import effective_location_hours


def fetch_intraday_demo(
    database_url: str,
    account_id: str,
    location_id: str,
    business_date: date,
) -> dict[str, Any]:
    """Fetch a demo intraday service view for one business date."""

    weekday = business_date.weekday()
    with account_connection(database_url, account_id) as conn:
        location = fetch_one(
            conn,
            """
            SELECT open_days
            FROM locations
            WHERE account_id = %s AND location_id = %s
            """,
            (account_id, location_id),
        )
        hours_rows = fetch_all(
            conn,
            """
            SELECT day_of_week, is_open, open_time, close_time,
                   effective_from, effective_to, source
            FROM location_hours
            WHERE account_id = %s
              AND location_id = %s
              AND day_of_week = %s
              AND effective_from <= %s
              AND (effective_to IS NULL OR effective_to > %s)
            ORDER BY effective_from DESC
            LIMIT 1
            """,
            (account_id, location_id, weekday, business_date, business_date),
        )
        daily_row = fetch_one(
            conn,
            """
            SELECT date, is_open, drinks_sold, input_source
            FROM daily_metrics
            WHERE account_id = %s AND location_id = %s AND date = %s
            """,
            (account_id, location_id, business_date),
        )
        history_rows = fetch_all(
            conn,
            """
            SELECT date, drinks_sold
            FROM daily_metrics
            WHERE account_id = %s
              AND location_id = %s
              AND date < %s
              AND is_open = true
              AND input_source <> 'imputed'
              AND drinks_sold IS NOT NULL
            ORDER BY date DESC
            LIMIT 56
            """,
            (account_id, location_id, business_date),
        )
        sellouts = fetch_all(
            conn,
            """
            SELECT category, sold, prepared, time_last_sale
            FROM daily_category_metrics
            WHERE account_id = %s
              AND location_id = %s
              AND date = %s
              AND sold_out = true
            ORDER BY time_last_sale NULLS LAST, category
            """,
            (account_id, location_id, business_date),
        )

    open_days = [] if location is None else list(location.get("open_days") or [])
    hours = effective_location_hours(hours_rows, business_date, open_days)
    expected_drinks, expected_source = expected_intraday_drinks(
        daily_row,
        history_rows,
        business_date,
    )
    return {
        "business_date": business_date,
        "hours": hours,
        "expected_drinks": expected_drinks,
        "expected_source": expected_source,
        "curve": build_intraday_pressure_curve(
            hours.get("open_time"),
            hours.get("close_time"),
            expected_drinks,
        ),
        "sellouts": sellouts,
    }


def expected_intraday_drinks(
    daily_row: dict[str, Any] | None,
    history_rows: list[dict[str, Any]],
    business_date: date,
) -> tuple[int, str]:
    """Return observed or trailing expected drinks for the intraday demo."""

    if (
        daily_row is not None
        and daily_row.get("is_open") is True
        and daily_row.get("input_source") != "imputed"
        and daily_row.get("drinks_sold") is not None
    ):
        return max(0, int(daily_row["drinks_sold"])), "observed closeout"

    same_weekday = [
        int(row["drinks_sold"])
        for row in history_rows
        if _as_date(row["date"]).weekday() == business_date.weekday()
    ][:8]
    if same_weekday:
        return round(sum(same_weekday) / len(same_weekday)), "same-weekday history"

    recent = [int(row["drinks_sold"]) for row in history_rows[:14]]
    if recent:
        return round(sum(recent) / len(recent)), "recent history"

    return 100, "demo fallback"


def build_intraday_pressure_curve(
    open_time: Any,
    close_time: Any,
    expected_drinks: int,
) -> list[dict[str, Any]]:
    """Build a synthetic half-hour service-pressure curve for the demo panel."""

    start = _minutes_from_time(open_time)
    end = _minutes_from_time(close_time)
    if start is None or end is None or end <= start:
        return []

    bucket_minutes = 30
    bucket_count = max(1, math.ceil((end - start) / bucket_minutes))
    buckets: list[tuple[int, int, float]] = []
    for index in range(bucket_count):
        bucket_start = start + index * bucket_minutes
        bucket_end = min(bucket_start + bucket_minutes, end)
        center = (bucket_start + bucket_end) / 2
        progress = (center - start) / max(end - start, 1)
        buckets.append((bucket_start, bucket_end, _daypart_weight(progress)))

    total_weight = sum(weight for _bucket_start, _bucket_end, weight in buckets)
    mean_weight = total_weight / len(buckets)
    expected = max(float(expected_drinks), 0.0)
    return [
        {
            "time": _format_minutes(bucket_start),
            "expected_drinks": round(expected * weight / total_weight, 1),
            "pressure_index": round(weight / mean_weight * 100),
        }
        for bucket_start, _bucket_end, weight in buckets
    ]


def _minutes_from_time(value: Any) -> int | None:
    """Convert a time-like value into minutes after midnight."""

    if value is None or pd.isna(value):
        return None
    if isinstance(value, time):
        return value.hour * 60 + value.minute
    if isinstance(value, datetime):
        return value.hour * 60 + value.minute
    if isinstance(value, pd.Timestamp):
        return int(value.hour) * 60 + int(value.minute)
    if isinstance(value, str):
        parts = value.split(":")
        if len(parts) >= 2:
            return int(parts[0]) * 60 + int(parts[1])
    raise ValueError(f"Unsupported time value: {value!r}")


def _format_minutes(minutes: int) -> str:
    """Format minutes after midnight as HH:MM."""

    hour, minute = divmod(minutes, 60)
    return f"{hour:02d}:{minute:02d}"


def _daypart_weight(progress: float) -> float:
    """Return a demo cafe traffic weight for a point in the service day."""

    morning = 1.15 * math.exp(-((progress - 0.28) / 0.18) ** 2)
    lunch = 1.55 * math.exp(-((progress - 0.66) / 0.20) ** 2)
    late = 0.35 * math.exp(-((progress - 0.88) / 0.16) ** 2)
    return 0.35 + morning + lunch + late

