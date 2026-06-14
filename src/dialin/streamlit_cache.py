"""Streamlit read caches for remote database-backed app views."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any, TypedDict, cast

import pandas as pd
import psycopg
import streamlit as st
from psycopg.rows import dict_row

from dialin import repository
from dialin.db import account_connection, fetch_all, fetch_one
from dialin.demo_truth import load_truth_demand as _load_truth_demand

READ_CACHE_TTL_SECONDS = 300


class AppBootstrap(TypedDict):
    """Startup data fetched through one remote database connection."""

    locations: list[dict[str, Any]]
    latest_date: date | None


class TodayPayload(TypedDict):
    """Today view data fetched through one remote database connection."""

    recommendations: list[dict[str, Any]]
    context: dict[str, Any]
    flow: dict[str, Any]


@st.cache_data(ttl=READ_CACHE_TTL_SECONDS, show_spinner=False)
def app_bootstrap(
    database_url: str,
    account_id: str,
    app_role: str,
) -> AppBootstrap:
    """Fetch startup role, location, and latest-date data with one connection."""

    with psycopg.connect(database_url, row_factory=dict_row) as conn, conn.transaction():
        current = conn.execute("SELECT current_user AS user_name").fetchone()
        user_name = "" if current is None else str(current["user_name"])
        if user_name != app_role:
            raise RuntimeError(
                f"DATABASE_URL must use the low-privilege {app_role!r} role; "
                f"got {user_name!r}."
            )

        conn.execute("SELECT set_config('app.current_account_id', %s, true)", (account_id,))
        locations = fetch_all(
            conn,
            """
            SELECT account_id, location_id, name, timezone, city, country
            FROM locations
            WHERE account_id = %s
            ORDER BY name
            """,
            (account_id,),
        )
        latest_date = None
        if locations:
            latest_row = fetch_one(
                conn,
                """
                SELECT max(date) AS latest_date
                FROM daily_metrics
                WHERE account_id = %s AND location_id = %s AND is_open = true
                """,
                (account_id, locations[0]["location_id"]),
            )
            if latest_row is not None and latest_row["latest_date"] is not None:
                latest_date = cast(date, latest_row["latest_date"])
    return {"locations": locations, "latest_date": latest_date}


@st.cache_data(ttl=READ_CACHE_TTL_SECONDS, show_spinner=False)
def list_locations(database_url: str, account_id: str) -> list[dict[str, Any]]:
    """Return cached locations visible to one account."""

    return repository.list_locations(database_url, account_id)


@st.cache_data(ttl=READ_CACHE_TTL_SECONDS, show_spinner=False)
def latest_business_date(
    database_url: str,
    account_id: str,
    location_id: str,
) -> date | None:
    """Return the cached latest open business date."""

    return repository.latest_business_date(database_url, account_id, location_id)


@st.cache_data(ttl=READ_CACHE_TTL_SECONDS, show_spinner=False)
def fetch_recommendations_for_date(
    database_url: str,
    account_id: str,
    location_id: str,
    target_date: date,
) -> list[dict[str, Any]]:
    """Return cached recommendation rows for one date."""

    return repository.fetch_recommendations_for_date(
        database_url,
        account_id,
        location_id,
        target_date,
    )


@st.cache_data(ttl=READ_CACHE_TTL_SECONDS, show_spinner=False)
def fetch_recommendation_context(
    database_url: str,
    account_id: str,
    location_id: str,
    target_date: date,
) -> dict[str, Any]:
    """Return cached weather and event inputs for one recommendation date."""

    return repository.fetch_recommendation_context(
        database_url,
        account_id,
        location_id,
        target_date,
    )


@st.cache_data(ttl=READ_CACHE_TTL_SECONDS, show_spinner=False)
def fetch_intraday_demo(
    database_url: str,
    account_id: str,
    location_id: str,
    business_date: date,
) -> dict[str, Any]:
    """Return cached service-flow data for one business date."""

    return repository.fetch_intraday_demo(database_url, account_id, location_id, business_date)


@st.cache_data(ttl=READ_CACHE_TTL_SECONDS, show_spinner=False)
def fetch_today_payload(
    database_url: str,
    account_id: str,
    location_id: str,
    target_date: date,
) -> TodayPayload:
    """Return all Today-view data through one account-scoped connection."""

    weekday = target_date.weekday()
    with account_connection(database_url, account_id) as conn:
        recommendations = fetch_all(
            conn,
            """
            SELECT *
            FROM recommendations
            WHERE account_id = %s AND location_id = %s AND date = %s
            ORDER BY category
            """,
            (account_id, location_id, target_date),
        )
        weather = fetch_one(
            conn,
            """
            SELECT *
            FROM weather
            WHERE account_id = %s AND location_id = %s AND date = %s
            """,
            (account_id, location_id, target_date),
        )
        events = fetch_all(
            conn,
            """
            SELECT event_name, event_type, impact_score, source, confidence
            FROM events
            WHERE account_id = %s AND location_id = %s AND date = %s
            ORDER BY impact_score DESC, event_name
            """,
            (account_id, location_id, target_date),
        )
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
            (account_id, location_id, weekday, target_date, target_date),
        )
        daily_row = fetch_one(
            conn,
            """
            SELECT date, is_open, drinks_sold, input_source
            FROM daily_metrics
            WHERE account_id = %s AND location_id = %s AND date = %s
            """,
            (account_id, location_id, target_date),
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
            (account_id, location_id, target_date),
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
            (account_id, location_id, target_date),
        )

    open_days = [] if location is None else list(location.get("open_days") or [])
    hours = repository.effective_location_hours(hours_rows, target_date, open_days)
    expected_drinks, expected_source = repository.expected_intraday_drinks(
        daily_row,
        history_rows,
        target_date,
    )
    return {
        "recommendations": recommendations,
        "context": {"weather": weather, "events": events},
        "flow": {
            "business_date": target_date,
            "hours": hours,
            "expected_drinks": expected_drinks,
            "expected_source": expected_source,
            "curve": repository.build_intraday_pressure_curve(
                hours.get("open_time"),
                hours.get("close_time"),
                expected_drinks,
            ),
            "sellouts": sellouts,
        },
    }


@st.cache_data(ttl=READ_CACHE_TTL_SECONDS, show_spinner=False)
def fetch_history_frames(
    database_url: str,
    account_id: str,
    location_id: str,
) -> dict[str, pd.DataFrame]:
    """Return cached history frames used by forms and model-quality views."""

    return repository.fetch_history_frames(database_url, account_id, location_id)


@st.cache_data(ttl=READ_CACHE_TTL_SECONDS, show_spinner=False)
def scorecard(database_url: str, account_id: str, location_id: str) -> dict[str, Any]:
    """Return cached observed scorecard rows and summary values."""

    return repository.scorecard(database_url, account_id, location_id)


@st.cache_data(ttl=READ_CACHE_TTL_SECONDS, show_spinner=False)
def fetch_recommendation_outcomes(
    database_url: str,
    account_id: str,
    location_id: str,
) -> list[dict[str, Any]]:
    """Return cached recommendation outcomes for model-quality scoring."""

    return repository.fetch_recommendation_outcomes(database_url, account_id, location_id)


@st.cache_data(ttl=READ_CACHE_TTL_SECONDS, show_spinner=False)
def fetch_category_economics(
    database_url: str,
    account_id: str,
    location_id: str,
    as_of: date,
) -> list[dict[str, Any]]:
    """Return cached category economics rows effective on one date."""

    return repository.fetch_category_economics(database_url, account_id, location_id, as_of)


@st.cache_data(ttl=READ_CACHE_TTL_SECONDS, show_spinner=False)
def fetch_data_corrections(
    database_url: str,
    account_id: str,
    location_id: str,
    limit: int = 25,
) -> list[dict[str, Any]]:
    """Return cached recent correction audit rows."""

    return repository.fetch_data_corrections(database_url, account_id, location_id, limit)


@st.cache_data(ttl=READ_CACHE_TTL_SECONDS, show_spinner=False)
def load_truth_demand(account_id: str, location_id: str) -> pd.DataFrame | None:
    """Return cached demo truth-demand fixture data."""

    return _load_truth_demand(account_id, location_id)


@st.cache_data(ttl=READ_CACHE_TTL_SECONDS, show_spinner=False)
def fetch_location_hours_plan(
    database_url: str,
    account_id: str,
    location_id: str,
    as_of: date,
) -> list[dict[str, Any]]:
    """Return cached active weekly opening-hours plan."""

    return repository.fetch_location_hours_plan(database_url, account_id, location_id, as_of)


@st.cache_data(ttl=READ_CACHE_TTL_SECONDS, show_spinner=False)
def fetch_events_for_window(
    database_url: str,
    account_id: str,
    location_id: str,
    start_date: date,
    end_date: date,
) -> list[dict[str, Any]]:
    """Return cached logged events in a date window."""

    return repository.fetch_events_for_window(
        database_url,
        account_id,
        location_id,
        start_date,
        end_date,
    )


@st.cache_data(ttl=READ_CACHE_TTL_SECONDS, show_spinner=False)
def fetch_recent_pos_import_runs(
    database_url: str,
    account_id: str,
    location_id: str,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Return cached recent POS import summaries."""

    return repository.fetch_recent_pos_import_runs(database_url, account_id, location_id, limit)


_CACHED_READS: tuple[Callable[..., Any], ...] = (
    app_bootstrap,
    list_locations,
    latest_business_date,
    fetch_recommendations_for_date,
    fetch_recommendation_context,
    fetch_intraday_demo,
    fetch_today_payload,
    fetch_history_frames,
    scorecard,
    fetch_recommendation_outcomes,
    fetch_category_economics,
    fetch_data_corrections,
    load_truth_demand,
    fetch_location_hours_plan,
    fetch_events_for_window,
    fetch_recent_pos_import_runs,
)


def clear_cached_reads() -> None:
    """Clear cached remote reads after app writes change tenant data."""

    for cached_read in _CACHED_READS:
        clear = getattr(cached_read, "clear", None)
        if callable(clear):
            clear()
