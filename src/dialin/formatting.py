"""Pure display formatters shared across the Dial In app views.

These helpers carry no Streamlit or database dependency: given a value they
return owner-facing display text. Keeping them in one leaf module lets the
per-tab render code stay focused on layout instead of string plumbing.
"""

from __future__ import annotations

from datetime import date
from datetime import time as dt_time
from typing import Any

import pandas as pd


def format_service_window(hours: dict[str, Any]) -> str:
    """Format one hours row for the service-pressure panel."""

    if not hours.get("is_open"):
        return "Closed"
    open_label = format_clock(hours.get("open_time"))
    close_label = format_clock(hours.get("close_time"))
    return f"{open_label}-{close_label}"


def format_driver(driver: dict[str, Any]) -> str:
    """Format an engine driver as a readable lift instead of a raw multiplier."""

    name = str(driver.get("name", "driver"))
    multiplier = float(driver.get("multiplier", 1.0))
    return f"{name}: {format_lift(multiplier)}"


def format_lift(multiplier: float) -> str:
    """Format a multiplier as a signed percentage lift."""

    pct = round((multiplier - 1) * 100)
    if pct > 0:
        return f"+{pct}%"
    if pct < 0:
        return f"{pct}%"
    return "neutral"


def format_percent(value: float) -> str:
    """Format a ratio as a whole percentage."""

    return f"{round(value * 100)}%"


def season_label(target_date: date) -> str:
    """Return a compact tourism-season label for the demo calendar."""

    if target_date.month in {6, 7, 8}:
        return "High season"
    if target_date.month in {3, 4, 5, 9, 10, 12}:
        return "Mid season"
    return "Low season"


def format_timestamp(value: Any) -> str:
    """Format a timestamp-like value for compact Streamlit captions."""

    if value is None or pd.isna(value):
        return "unknown"
    timestamp = pd.Timestamp(value)
    return f"{timestamp.strftime('%b')} {timestamp.day} {timestamp.strftime('%H:%M')}"


def format_clock(value: Any) -> str:
    """Format a time-like value as HH:MM."""

    minutes = minutes_from_clock(value)
    if minutes is None:
        return "unknown"
    hour, minute = divmod(minutes, 60)
    return f"{hour:02d}:{minute:02d}"


def minutes_from_clock(value: Any) -> int | None:
    """Convert a timestamp or time value into local minutes after midnight."""

    if value is None or pd.isna(value):
        return None
    if isinstance(value, dt_time):
        return value.hour * 60 + value.minute
    timestamp = pd.Timestamp(value)
    return int(timestamp.hour) * 60 + int(timestamp.minute)


def format_minutes_before_close(minutes: int | None) -> str:
    """Format a sellout timing delta against close time."""

    if minutes is None:
        return "unknown"
    if minutes < 0:
        return f"{abs(minutes)} min after close"
    if minutes == 0:
        return "at close"
    return f"{minutes} min before close"


def format_source_label(value: Any) -> str:
    """Format source labels without title-case hyphen artifacts."""

    return str(value).replace("-", " ").replace("_", " ").strip().capitalize()


def format_adherence(value: Any) -> str:
    """Format recommendation attribution for charts and tables."""

    if value is True:
        return "Followed"
    if value is False:
        return "Overridden"
    return "Unattributed"


def weekday_labels() -> tuple[str, ...]:
    """Return weekday labels in Postgres weekday order."""

    return ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def time_value(value: Any, fallback: dt_time) -> dt_time:
    """Return a time value from database output or a fallback."""

    if isinstance(value, dt_time):
        return value
    if value is None or pd.isna(value):
        return fallback
    timestamp = pd.Timestamp(value)
    return dt_time(int(timestamp.hour), int(timestamp.minute))


def time_from_timestamp(value: Any) -> dt_time | None:
    """Return the local clock component from a timestamp-like value."""

    if value is None or pd.isna(value):
        return None
    if isinstance(value, dt_time):
        return value
    timestamp = pd.Timestamp(value)
    return dt_time(int(timestamp.hour), int(timestamp.minute))
