"""Streamlit read caches for remote database-backed app views."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

import pandas as pd
import streamlit as st

from dialin import repository
from dialin.demo_truth import load_truth_demand as _load_truth_demand

READ_CACHE_TTL_SECONDS = 300


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
    list_locations,
    latest_business_date,
    fetch_recommendations_for_date,
    fetch_recommendation_context,
    fetch_intraday_demo,
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
