"""Observed-only parquet loader for Dial In Postgres targets."""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from datetime import date, time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from dialin.db import admin_connection, execute_many
from dialin.validation import ensure_no_truth_columns

LOAD_ORDER = (
    "accounts",
    "account_members",
    "locations",
    "location_hours",
    "daily_metrics",
    "daily_category_metrics",
    "weather",
    "events",
    "category_economics",
)

TABLE_COLUMNS: dict[str, tuple[str, ...]] = {
    "accounts": (
        "account_id",
        "name",
        "plan",
        "contributes_to_shared_layer",
        "cold_start_pool_opt_in",
        "pos_backfill_months",
        "created_at",
    ),
    "account_members": ("auth_subject", "account_id", "created_at"),
    "locations": (
        "account_id",
        "location_id",
        "name",
        "timezone",
        "city",
        "country",
        "open_days",
        "service_capacity_hint",
        "created_at",
    ),
    "location_hours": (
        "account_id",
        "location_id",
        "day_of_week",
        "is_open",
        "open_time",
        "close_time",
        "effective_from",
        "effective_to",
        "source",
        "created_at",
    ),
    "daily_metrics": (
        "account_id",
        "location_id",
        "date",
        "timezone",
        "is_open",
        "drinks_sold",
        "input_source",
        "menu_version",
        "recorded_at",
    ),
    "daily_category_metrics": (
        "account_id",
        "location_id",
        "date",
        "category",
        "sold",
        "prepared",
        "sold_out",
        "stockout_detected_by",
        "time_last_sale",
        "salvage_share_observed",
        "input_source",
    ),
    "weather": (
        "account_id",
        "location_id",
        "date",
        "temp_forecast",
        "temp_actual",
        "rain_forecast",
        "rain_actual",
        "wind",
        "condition",
        "forecast_made_at",
    ),
    "events": (
        "account_id",
        "location_id",
        "date",
        "event_name",
        "event_type",
        "impact_score",
        "source",
        "confidence",
    ),
    "category_economics": (
        "account_id",
        "location_id",
        "category",
        "retail_price",
        "unit_cogs",
        "salvage_share_default",
        "attached_drink_margin",
        "attach_and_balk_rate",
        "service_quantile",
        "effective_from",
        "effective_to",
    ),
}

CONFLICT_COLUMNS: dict[str, tuple[str, ...] | None] = {
    "accounts": ("account_id",),
    "account_members": ("auth_subject",),
    "locations": ("account_id", "location_id"),
    "location_hours": ("account_id", "location_id", "day_of_week", "effective_from"),
    "daily_metrics": ("account_id", "location_id", "date"),
    "daily_category_metrics": ("account_id", "location_id", "date", "category"),
    "weather": ("account_id", "location_id", "date"),
    "events": None,
    "category_economics": ("account_id", "location_id", "category", "effective_from"),
}


def load_observed_directory(
    database_url: str, observed_dir: Path, mode: str = "truncate-load"
) -> None:
    """Load observed parquet tables into Postgres without loading planted truth."""

    if mode not in {"truncate-load", "upsert"}:
        raise ValueError("mode must be 'truncate-load' or 'upsert'")

    frames = read_observed_frames(observed_dir)
    with admin_connection(database_url) as conn:
        if mode == "truncate-load":
            conn.execute(
                """
                TRUNCATE
                    data_corrections,
                    recommendations,
                    pos_import_errors,
                    pos_daily_sales,
                    pos_import_runs,
                    events,
                    weather,
                    daily_category_metrics,
                    daily_metrics,
                    category_economics,
                    location_hours,
                    locations,
                    account_members,
                    accounts
                RESTART IDENTITY CASCADE
                """
            )
        for table_name in LOAD_ORDER:
            frame = frames.get(table_name)
            if frame is None:
                continue
            rows = frame_to_rows(frame, TABLE_COLUMNS[table_name])
            if mode == "upsert" and CONFLICT_COLUMNS[table_name] is not None:
                query = _upsert_sql(
                    table_name, TABLE_COLUMNS[table_name], CONFLICT_COLUMNS[table_name]
                )
            else:
                query = _insert_sql(table_name, TABLE_COLUMNS[table_name])
            execute_many(conn, query, rows)


def read_observed_frames(observed_dir: Path) -> dict[str, pd.DataFrame]:
    """Read all observed parquet files and reject truth leakage."""

    if not observed_dir.exists():
        raise FileNotFoundError(f"observed directory does not exist: {observed_dir}")

    frames: dict[str, pd.DataFrame] = {}
    for table_name in LOAD_ORDER:
        path = observed_dir / f"{table_name}.parquet"
        if not path.exists():
            if table_name in {"account_members", "location_hours"}:
                continue
            raise FileNotFoundError(f"missing observed table: {path}")
        frame = pd.read_parquet(path)
        ensure_no_truth_columns(frame, table_name)
        _check_columns(frame, table_name, TABLE_COLUMNS[table_name])
        frames[table_name] = frame

    if "account_members" not in frames:
        frames["account_members"] = _default_account_members(frames["accounts"])
    if "location_hours" not in frames:
        frames["location_hours"] = _default_location_hours(frames["locations"])
    return frames


def frame_to_rows(frame: pd.DataFrame, columns: Sequence[str]) -> list[tuple[Any, ...]]:
    """Convert a DataFrame into DB-API row tuples with pandas nulls removed."""

    rows: list[tuple[Any, ...]] = []
    for record in frame.loc[:, list(columns)].to_dict(orient="records"):
        rows.append(tuple(_clean_value(record[column]) for column in columns))
    return rows


def _default_account_members(accounts: pd.DataFrame) -> pd.DataFrame:
    """Create demo auth-subject bindings when no explicit file is generated."""

    now = pd.Timestamp.now(tz="UTC")
    rows = []
    for account_id in accounts["account_id"].to_list():
        auth_subject = "demo" if account_id == "acct_fadri" else "dummy"
        rows.append({"auth_subject": auth_subject, "account_id": account_id, "created_at": now})
    return pd.DataFrame(rows)


def _default_location_hours(locations: pd.DataFrame) -> pd.DataFrame:
    """Create default demo hours when an older observed export lacks them."""

    rows: list[dict[str, Any]] = []
    for location in locations.to_dict(orient="records"):
        open_days = set(location["open_days"])
        for day_of_week in range(7):
            is_open = day_of_week in open_days
            rows.append(
                {
                    "account_id": location["account_id"],
                    "location_id": location["location_id"],
                    "day_of_week": day_of_week,
                    "is_open": is_open,
                    "open_time": time(8, 0) if is_open else None,
                    "close_time": time(16, 0) if is_open else None,
                    "effective_from": date(2024, 1, 1),
                    "effective_to": None,
                    "source": "demo_seed",
                    "created_at": pd.Timestamp.now(tz="UTC"),
                }
            )
    return pd.DataFrame(rows)


def _check_columns(frame: pd.DataFrame, table_name: str, columns: Iterable[str]) -> None:
    """Ensure an observed table has the columns required by the loader."""

    missing = set(columns) - set(frame.columns)
    if missing:
        raise ValueError(f"{table_name} missing columns: {sorted(missing)}")


def _clean_value(value: Any) -> Any:
    """Convert pandas/numpy nulls and scalars to plain values psycopg can bind."""

    if value is pd.NaT:
        return None
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, float) and math.isnan(value):
        return None
    if pd.isna(value) is True:
        return None
    if hasattr(value, "item") and not isinstance(value, list):
        try:
            return value.item()
        except ValueError:
            return value
    return value


def _insert_sql(table_name: str, columns: Sequence[str]) -> str:
    """Build an INSERT statement for a known table and column list."""

    column_sql = ", ".join(columns)
    placeholders = ", ".join(["%s"] * len(columns))
    return f"INSERT INTO {table_name} ({column_sql}) VALUES ({placeholders})"


def _upsert_sql(
    table_name: str,
    columns: Sequence[str],
    conflict_columns: Sequence[str] | None,
) -> str:
    """Build an INSERT .. ON CONFLICT statement for a known table."""

    if conflict_columns is None:
        return _insert_sql(table_name, columns)
    column_sql = ", ".join(columns)
    placeholders = ", ".join(["%s"] * len(columns))
    conflict_sql = ", ".join(conflict_columns)
    update_columns = [column for column in columns if column not in conflict_columns]
    update_sql = ", ".join(f"{column} = EXCLUDED.{column}" for column in update_columns)
    return (
        f"INSERT INTO {table_name} ({column_sql}) VALUES ({placeholders}) "
        f"ON CONFLICT ({conflict_sql}) DO UPDATE SET {update_sql}"
    )
