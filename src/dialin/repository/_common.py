"""Shared low-level helpers for the repository package."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, cast

import pandas as pd


def _as_date(value: Any) -> date:
    """Convert a date-like value into a plain date."""

    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    return cast(date, pd.Timestamp(value).date())

