"""Calendar event reads and manual event entry."""

from __future__ import annotations

from datetime import date
from typing import Any

from dialin.db import account_connection, fetch_all


def fetch_events_for_window(
    database_url: str,
    account_id: str,
    location_id: str,
    start_date: date,
    end_date: date,
) -> list[dict[str, Any]]:
    """Fetch logged events in a date window for setup and context review."""

    with account_connection(database_url, account_id) as conn:
        return fetch_all(
            conn,
            """
            SELECT date, event_name, event_type, impact_score, source, confidence
            FROM events
            WHERE account_id = %s
              AND location_id = %s
              AND date BETWEEN %s AND %s
            ORDER BY date, impact_score DESC, event_name
            """,
            (account_id, location_id, start_date, end_date),
        )


def insert_manual_event(
    database_url: str,
    account_id: str,
    location_id: str,
    business_date: date,
    event_name: str,
    event_type: str,
    impact_score: float,
    confidence: str,
    source: str = "owner_confirmed",
) -> None:
    """Insert one owner-confirmed local event used by future recommendations."""

    clean_name = event_name.strip()
    clean_type = event_type.strip() or "local"
    if not clean_name:
        raise ValueError("Event name cannot be blank.")
    if impact_score < 0:
        raise ValueError("Impact score must be non-negative.")
    if confidence not in {"Low", "Medium", "High"}:
        raise ValueError("Confidence must be Low, Medium, or High.")

    with account_connection(database_url, account_id) as conn:
        conn.execute(
            """
            INSERT INTO events (
                account_id,
                location_id,
                date,
                event_name,
                event_type,
                impact_score,
                source,
                confidence
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                account_id,
                location_id,
                business_date,
                clean_name,
                clean_type,
                impact_score,
                source,
                confidence,
            ),
        )

