"""Demo-only freshness helpers for synthetic tenant data."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, cast

import pandas as pd

from dialin.db import account_connection, execute_many, fetch_one
from dialin.generator import GeneratedDataset, generate_synthetic_dataset
from dialin.loader import TABLE_COLUMNS, frame_to_rows
from dialin.repository import (
    fetch_next_open_business_date,
    generate_and_store_recommendations,
)

DEMO_SEED = 20260531
DEMO_LOOKAHEAD_DAYS = 1
DEMO_LOCATION_PAIRS: tuple[tuple[str, str], ...] = (
    ("acct_fadri", "loc_fadri_main"),
    ("acct_dummy", "loc_dummy_main"),
)
DEMO_LOCATIONS: frozenset[tuple[str, str]] = frozenset(DEMO_LOCATION_PAIRS)

_CONFLICT_COLUMNS: dict[str, tuple[str, ...]] = {
    "daily_metrics": ("account_id", "location_id", "date"),
    "daily_category_metrics": ("account_id", "location_id", "date", "category"),
    "weather": ("account_id", "location_id", "date"),
}


@dataclass(frozen=True)
class DemoFreshnessResult:
    """Summary of demo rows appended and recommendations refreshed."""

    observed_dates: tuple[date, ...]
    context_dates: tuple[date, ...]
    recommendation_dates: tuple[date, ...]
    recommendation_rows: int

    @classmethod
    def empty(cls) -> DemoFreshnessResult:
        """Return a no-op freshness result."""

        return cls(
            observed_dates=(),
            context_dates=(),
            recommendation_dates=(),
            recommendation_rows=0,
        )

    @property
    def changed(self) -> bool:
        """Return true when the freshness pass wrote or refreshed anything."""

        return bool(
            self.observed_dates or self.context_dates or self.recommendation_rows
        )


def is_demo_location(account_id: str, location_id: str) -> bool:
    """Return true when a tenant/location is one of the seeded demo locations."""

    return (account_id, location_id) in DEMO_LOCATIONS


def latest_metric_date(database_url: str, account_id: str, location_id: str) -> date | None:
    """Return the latest generated calendar date, including closed days."""

    with account_connection(database_url, account_id) as conn:
        row = fetch_one(
            conn,
            """
            SELECT max(date) AS latest_date
            FROM daily_metrics
            WHERE account_id = %s AND location_id = %s
            """,
            (account_id, location_id),
        )
    if row is None or row["latest_date"] is None:
        return None
    return cast(date, row["latest_date"])


def observed_dates_to_append(latest_calendar_date: date, today: date) -> tuple[date, ...]:
    """Return missing historical demo dates that should be inserted."""

    if latest_calendar_date >= today:
        return ()
    return _inclusive_dates(latest_calendar_date + timedelta(days=1), today)


def context_dates_to_ensure(
    latest_calendar_date: date,
    today: date,
    lookahead_end: date | None = None,
) -> tuple[date, ...]:
    """Return weather/event dates needed for current and next prep-day recommendations.

    ``lookahead_end`` extends the horizon to the nearest open prep day so the
    Today view's target always has forecast context, even across a closed day.
    """

    end = _lookahead_end_or_default(today, lookahead_end)
    start = latest_calendar_date + timedelta(days=1) if latest_calendar_date < today else today
    return _inclusive_dates(start, end)


def recommendation_refresh_dates(
    latest_calendar_date: date,
    today: date,
    lookahead_end: date | None = None,
) -> tuple[date, ...]:
    """Return recommendation dates to refresh after synthetic data is extended.

    ``lookahead_end`` reaches the nearest open prep day so its recommendation is
    stored even when the next calendar day is closed.
    """

    end = _lookahead_end_or_default(today, lookahead_end)
    start = latest_calendar_date if latest_calendar_date < today else today
    return _inclusive_dates(start, end)


def _lookahead_end_or_default(today: date, lookahead_end: date | None) -> date:
    """Return the horizon end, never earlier than the fixed one-day lookahead."""

    default_end = today + timedelta(days=DEMO_LOOKAHEAD_DAYS)
    if lookahead_end is None:
        return default_end
    return max(default_end, lookahead_end)


def ensure_demo_data_fresh(
    database_url: str,
    account_id: str,
    location_id: str,
    today: date,
    seed: int = DEMO_SEED,
) -> DemoFreshnessResult:
    """Append missing synthetic demo days and refresh recommendation rows."""

    if not is_demo_location(account_id, location_id):
        return DemoFreshnessResult.empty()

    latest_calendar_date = latest_metric_date(database_url, account_id, location_id)
    if latest_calendar_date is None:
        return DemoFreshnessResult.empty()

    lookahead_end = _resolve_lookahead_end(database_url, account_id, location_id, today)
    observed_dates = observed_dates_to_append(latest_calendar_date, today)
    context_dates = context_dates_to_ensure(latest_calendar_date, today, lookahead_end)
    recommendation_dates = recommendation_refresh_dates(
        latest_calendar_date, today, lookahead_end
    )

    if observed_dates or context_dates:
        dataset = generate_synthetic_dataset(seed=seed, end_date=lookahead_end)
        _append_generated_rows(
            database_url=database_url,
            account_id=account_id,
            location_id=location_id,
            dataset=dataset,
            observed_dates=observed_dates,
            context_dates=context_dates,
        )

    recommendation_rows = 0
    for target_date in recommendation_dates:
        recommendation_rows += len(
            generate_and_store_recommendations(
                database_url=database_url,
                account_id=account_id,
                location_id=location_id,
                target_date=target_date,
            )
        )

    return DemoFreshnessResult(
        observed_dates=observed_dates,
        context_dates=context_dates,
        recommendation_dates=recommendation_dates,
        recommendation_rows=recommendation_rows,
    )


def _resolve_lookahead_end(
    database_url: str,
    account_id: str,
    location_id: str,
    today: date,
) -> date:
    """Return the horizon end covering at least the nearest open prep day after today."""

    default_end = today + timedelta(days=DEMO_LOOKAHEAD_DAYS)
    next_open = fetch_next_open_business_date(database_url, account_id, location_id, today)
    if next_open is None:
        return default_end
    return max(default_end, next_open)


def _append_generated_rows(
    database_url: str,
    account_id: str,
    location_id: str,
    dataset: GeneratedDataset,
    observed_dates: Sequence[date],
    context_dates: Sequence[date],
) -> None:
    """Insert generated demo rows without overwriting existing operator data."""

    with account_connection(database_url, account_id) as conn:
        if observed_dates:
            _insert_table_rows(
                conn,
                dataset.observed,
                "daily_metrics",
                account_id,
                location_id,
                observed_dates,
            )
            _insert_table_rows(
                conn,
                dataset.observed,
                "daily_category_metrics",
                account_id,
                location_id,
                observed_dates,
            )
        if context_dates:
            _insert_table_rows(
                conn,
                dataset.observed,
                "weather",
                account_id,
                location_id,
                context_dates,
            )
            _insert_event_rows(
                conn,
                dataset.observed,
                account_id,
                location_id,
                context_dates,
            )


def _insert_table_rows(
    conn: Any,
    observed: Mapping[str, pd.DataFrame],
    table_name: str,
    account_id: str,
    location_id: str,
    dates: Sequence[date],
) -> None:
    """Insert generated rows for a conflict-keyed table."""

    frame = _scoped_rows(observed, table_name, account_id, location_id, dates)
    rows = frame_to_rows(frame, TABLE_COLUMNS[table_name])
    execute_many(
        conn,
        _insert_do_nothing_sql(table_name, TABLE_COLUMNS[table_name]),
        rows,
    )


def _insert_event_rows(
    conn: Any,
    observed: Mapping[str, pd.DataFrame],
    account_id: str,
    location_id: str,
    dates: Sequence[date],
) -> None:
    """Insert generated events while avoiding duplicate demo event labels."""

    columns = TABLE_COLUMNS["events"]
    frame = _scoped_rows(observed, "events", account_id, location_id, dates)
    rows = frame_to_rows(frame, columns)
    params: list[tuple[Any, ...]] = []
    for row in rows:
        record = dict(zip(columns, row, strict=True))
        params.append(
            (
                *row,
                record["account_id"],
                record["location_id"],
                record["date"],
                record["event_name"],
                record["event_type"],
            )
        )

    execute_many(conn, _event_insert_sql(columns), params)


def _scoped_rows(
    observed: Mapping[str, pd.DataFrame],
    table_name: str,
    account_id: str,
    location_id: str,
    dates: Sequence[date],
) -> pd.DataFrame:
    """Return generated rows scoped to one tenant/location and date set."""

    columns = TABLE_COLUMNS[table_name]
    frame = observed.get(table_name)
    if frame is None or frame.empty or not dates:
        return pd.DataFrame(columns=columns)
    selected_dates = set(dates)
    mask = (
        (frame["account_id"] == account_id)
        & (frame["location_id"] == location_id)
        & frame["date"].isin(selected_dates)
    )
    return frame.loc[mask, list(columns)].copy()


def _insert_do_nothing_sql(table_name: str, columns: Sequence[str]) -> str:
    """Build an insert statement that never overwrites existing generated rows."""

    column_sql = ", ".join(columns)
    placeholders = ", ".join(["%s"] * len(columns))
    conflict_columns = ", ".join(_CONFLICT_COLUMNS[table_name])
    return (
        f"INSERT INTO {table_name} ({column_sql}) VALUES ({placeholders}) "
        f"ON CONFLICT ({conflict_columns}) DO NOTHING"
    )


def _event_insert_sql(columns: Sequence[str]) -> str:
    """Build an event insert that treats matching labels as already present."""

    column_sql = ", ".join(columns)
    placeholders = ", ".join(["%s"] * len(columns))
    return (
        f"INSERT INTO events ({column_sql}) "
        f"SELECT {placeholders} "
        "WHERE NOT EXISTS ("
        "SELECT 1 FROM events "
        "WHERE account_id = %s "
        "AND location_id = %s "
        "AND date = %s "
        "AND event_name = %s "
        "AND event_type = %s"
        ")"
    )


def _inclusive_dates(start: date, end: date) -> tuple[date, ...]:
    """Return calendar dates from start through end, or an empty tuple."""

    if start > end:
        return ()
    days = (end - start).days
    return tuple(start + timedelta(days=offset) for offset in range(days + 1))
