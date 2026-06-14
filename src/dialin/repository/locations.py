"""Location and opening-hours reads and writes."""

from __future__ import annotations

from datetime import date, time, timedelta
from typing import Any

from dialin.db import account_connection, fetch_all, fetch_one
from dialin.repository._common import _as_date


def list_locations(database_url: str, account_id: str) -> list[dict[str, Any]]:
    """Return locations visible to one account."""

    with account_connection(database_url, account_id) as conn:
        return fetch_all(
            conn,
            """
            SELECT account_id, location_id, name, timezone, city, country
            FROM locations
            WHERE account_id = %s
            ORDER BY name
            """,
            (account_id,),
        )


def fetch_location_hours_plan(
    database_url: str,
    account_id: str,
    location_id: str,
    as_of: date,
) -> list[dict[str, Any]]:
    """Return the active weekly opening-hours plan for one location."""

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
        rows = fetch_all(
            conn,
            """
            SELECT DISTINCT ON (day_of_week)
                   day_of_week, is_open, open_time, close_time,
                   effective_from, effective_to, source
            FROM location_hours
            WHERE account_id = %s
              AND location_id = %s
              AND effective_from <= %s
              AND (effective_to IS NULL OR effective_to > %s)
            ORDER BY day_of_week, effective_from DESC
            """,
            (account_id, location_id, as_of, as_of),
        )

    open_days = [] if location is None else list(location.get("open_days") or [])
    rows_by_day = {int(row["day_of_week"]): row for row in rows}
    plan: list[dict[str, Any]] = []
    for day_of_week in range(7):
        if day_of_week in rows_by_day:
            plan.append(rows_by_day[day_of_week])
            continue
        sample_date = as_of + timedelta(days=(day_of_week - as_of.weekday()) % 7)
        plan.append(effective_location_hours([], sample_date, open_days=open_days))
    return sorted(plan, key=lambda row: int(row["day_of_week"]))


def upsert_location_hours(
    database_url: str,
    account_id: str,
    location_id: str,
    day_of_week: int,
    is_open: bool,
    open_time: time | None,
    close_time: time | None,
    effective_from: date,
    source: str = "owner_confirmed",
) -> None:
    """Insert or update one effective-dated opening-hours row."""

    if day_of_week < 0 or day_of_week > 6:
        raise ValueError("day_of_week must be between 0 and 6.")
    if source not in {"demo_seed", "owner_confirmed", "corrected"}:
        raise ValueError("source must be demo_seed, owner_confirmed, or corrected.")
    if is_open and (open_time is None or close_time is None):
        raise ValueError("Open days need both opening and closing times.")
    if not is_open:
        open_time = None
        close_time = None
    if open_time is not None and close_time is not None and close_time <= open_time:
        raise ValueError("Closing time must be after opening time.")

    with account_connection(database_url, account_id) as conn:
        next_row = fetch_one(
            conn,
            """
            SELECT min(effective_from) AS next_effective_from
            FROM location_hours
            WHERE account_id = %s
              AND location_id = %s
              AND day_of_week = %s
              AND effective_from > %s
            """,
            (account_id, location_id, day_of_week, effective_from),
        )
        next_effective_from = (
            None if next_row is None else next_row.get("next_effective_from")
        )
        conn.execute(
            """
            UPDATE location_hours
            SET effective_to = %s
            WHERE account_id = %s
              AND location_id = %s
              AND day_of_week = %s
              AND effective_from < %s
              AND (effective_to IS NULL OR effective_to > %s)
            """,
            (
                effective_from,
                account_id,
                location_id,
                day_of_week,
                effective_from,
                effective_from,
            ),
        )
        conn.execute(
            """
            INSERT INTO location_hours (
                account_id,
                location_id,
                day_of_week,
                is_open,
                open_time,
                close_time,
                effective_from,
                effective_to,
                source
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (account_id, location_id, day_of_week, effective_from)
            DO UPDATE SET
                is_open = EXCLUDED.is_open,
                open_time = EXCLUDED.open_time,
                close_time = EXCLUDED.close_time,
                effective_to = EXCLUDED.effective_to,
                source = EXCLUDED.source
            """,
            (
                account_id,
                location_id,
                day_of_week,
                is_open,
                open_time,
                close_time,
                effective_from,
                next_effective_from,
                source,
            ),
        )


def effective_location_hours(
    rows: list[dict[str, Any]],
    business_date: date,
    open_days: list[int] | None = None,
) -> dict[str, Any]:
    """Return the active opening-hours row or a conservative location fallback."""

    active_rows = [
        row
        for row in rows
        if int(row["day_of_week"]) == business_date.weekday()
        and _as_date(row["effective_from"]) <= business_date
        and (row.get("effective_to") is None or _as_date(row["effective_to"]) > business_date)
    ]
    if active_rows:
        row = sorted(active_rows, key=lambda item: _as_date(item["effective_from"]))[-1]
        return {
            "day_of_week": business_date.weekday(),
            "is_open": bool(row["is_open"]),
            "open_time": row.get("open_time"),
            "close_time": row.get("close_time"),
            "source": str(row.get("source") or "demo_seed"),
        }

    fallback_open = business_date.weekday() in set(open_days or [])
    return {
        "day_of_week": business_date.weekday(),
        "is_open": fallback_open,
        "open_time": time(8, 0) if fallback_open else None,
        "close_time": time(16, 0) if fallback_open else None,
        "source": "location_open_days",
    }

