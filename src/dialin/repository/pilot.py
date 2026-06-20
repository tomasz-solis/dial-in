"""Pilot readiness: baseline/live windows and the pilot setup profile.

These back Phase 12 of the build plan. ``pilot_windows`` lets measurement be
partitioned into the café's own pre-Dial-In baseline versus the live window
(PRD section 14). ``pilot_profile`` records the operational and economic context
(PRD sections 6.5, 17.1) that must exist before any value claim is credible.
Neither feeds a recommendation; they are advisory metadata.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from dialin.db import account_connection, fetch_all, fetch_one
from dialin.repository._common import _as_date

PILOT_PHASES = ("baseline", "live")

# Pilot setup checklist fields (PRD sections 6.5, 17.1). ``kind`` drives the
# Streamlit widget and how the value is rendered in the exported report.
PILOT_CHECKLIST_FIELDS: tuple[dict[str, str], ...] = (
    {"key": "open_days_per_week", "label": "Open days per week", "kind": "number"},
    {"key": "food_revenue_share", "label": "Food share of revenue (%)", "kind": "number"},
    {"key": "weekend_sellout_frequency", "label": "Weekend sellout frequency", "kind": "text"},
    {"key": "typical_sellout_time", "label": "Typical sellout time", "kind": "text"},
    {"key": "waste_handling", "label": "How leftovers are handled", "kind": "text"},
    {"key": "economics_confirmed", "label": "Category economics confirmed", "kind": "bool"},
    {"key": "pos_export_available", "label": "POS export available", "kind": "bool"},
)


def fetch_pilot_windows(
    database_url: str, account_id: str, location_id: str
) -> list[dict[str, Any]]:
    """Return the pilot phase windows for one location, newest first."""

    with account_connection(database_url, account_id) as conn:
        return fetch_all(
            conn,
            """
            SELECT pilot_window_id, phase, start_date, end_date, note
            FROM pilot_windows
            WHERE account_id = %s AND location_id = %s
            ORDER BY start_date DESC, phase
            """,
            (account_id, location_id),
        )


def upsert_pilot_window(
    database_url: str,
    account_id: str,
    location_id: str,
    phase: str,
    start_date: date,
    end_date: date | None = None,
    note: str | None = None,
) -> None:
    """Insert or replace one pilot phase window after validating it."""

    if phase not in PILOT_PHASES:
        raise ValueError(f"phase must be one of {PILOT_PHASES}")
    if end_date is not None and end_date < start_date:
        raise ValueError("end_date must not precede start_date")
    with account_connection(database_url, account_id) as conn:
        other_windows = fetch_all(
            conn,
            """
            SELECT phase, start_date, end_date
            FROM pilot_windows
            WHERE account_id = %s AND location_id = %s AND phase <> %s
            """,
            (account_id, location_id, phase),
        )
        if any(_windows_overlap(start_date, end_date, row) for row in other_windows):
            raise ValueError("Pilot windows must not overlap.")
        conn.execute(
            """
            INSERT INTO pilot_windows
                (account_id, location_id, phase, start_date, end_date, note)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (account_id, location_id, phase)
            DO UPDATE SET
                start_date = EXCLUDED.start_date,
                end_date = EXCLUDED.end_date,
                note = EXCLUDED.note
            """,
            (account_id, location_id, phase, start_date, end_date, note),
        )


def fetch_pilot_profile(
    database_url: str, account_id: str, location_id: str
) -> dict[str, Any] | None:
    """Return the saved pilot setup profile for one location, if any."""

    with account_connection(database_url, account_id) as conn:
        return fetch_one(
            conn,
            """
            SELECT responses, values_source, updated_at
            FROM pilot_profile
            WHERE account_id = %s AND location_id = %s
            """,
            (account_id, location_id),
        )


def upsert_pilot_profile(
    database_url: str,
    account_id: str,
    location_id: str,
    responses: dict[str, Any],
    values_source: str = "owner_confirmed",
) -> None:
    """Insert or update the pilot setup profile for one location."""

    if values_source not in {"default", "owner_confirmed", "corrected"}:
        raise ValueError("values_source must be default, owner_confirmed, or corrected.")
    with account_connection(database_url, account_id) as conn:
        conn.execute(
            """
            INSERT INTO pilot_profile (account_id, location_id, responses, values_source)
            VALUES (%s, %s, %s::jsonb, %s)
            ON CONFLICT (account_id, location_id)
            DO UPDATE SET
                responses = EXCLUDED.responses,
                values_source = EXCLUDED.values_source,
                updated_at = now()
            """,
            (account_id, location_id, json.dumps(responses), values_source),
        )


def phase_for_date(target: date, windows: list[dict[str, Any]]) -> str | None:
    """Return the pilot phase covering a date, preferring the latest start."""

    covering = [
        window
        for window in windows
        if _as_date(window["start_date"]) <= target
        and (window["end_date"] is None or target <= _as_date(window["end_date"]))
    ]
    if not covering:
        return None
    latest = max(covering, key=lambda window: _as_date(window["start_date"]))
    return str(latest["phase"])


def _windows_overlap(
    start_date: date,
    end_date: date | None,
    other: dict[str, Any],
) -> bool:
    """Return whether two inclusive pilot date ranges overlap."""

    other_start = _as_date(other["start_date"])
    other_end = None if other["end_date"] is None else _as_date(other["end_date"])
    ends_after_other_starts = end_date is None or end_date >= other_start
    other_ends_after_start = other_end is None or other_end >= start_date
    return ends_after_other_starts and other_ends_after_start
