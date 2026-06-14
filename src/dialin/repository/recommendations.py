"""Recommendation reads, persistence, and the generate-and-store workflow."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from dialin.db import account_connection, fetch_all, fetch_one
from dialin.engine import RecommendationResult, build_recommendations
from dialin.repository.reads import fetch_history_frames


def fetch_latest_recommendations(
    database_url: str,
    account_id: str,
    location_id: str,
) -> list[dict[str, Any]]:
    """Fetch the most recent stored recommendation set."""

    with account_connection(database_url, account_id) as conn:
        row = fetch_one(
            conn,
            """
            SELECT max(date) AS target_date
            FROM recommendations
            WHERE account_id = %s AND location_id = %s
            """,
            (account_id, location_id),
        )
        if row is None or row["target_date"] is None:
            return []
        return fetch_all(
            conn,
            """
            SELECT *
            FROM recommendations
            WHERE account_id = %s AND location_id = %s AND date = %s
            ORDER BY category
            """,
            (account_id, location_id, row["target_date"]),
        )


def fetch_recommendations_for_date(
    database_url: str,
    account_id: str,
    location_id: str,
    target_date: date,
) -> list[dict[str, Any]]:
    """Fetch stored recommendation rows for one target date."""

    with account_connection(database_url, account_id) as conn:
        return fetch_all(
            conn,
            """
            SELECT *
            FROM recommendations
            WHERE account_id = %s AND location_id = %s AND date = %s
            ORDER BY category
            """,
            (account_id, location_id, target_date),
        )


def fetch_recommendation_context(
    database_url: str,
    account_id: str,
    location_id: str,
    target_date: date,
) -> dict[str, Any]:
    """Fetch weather and event inputs used to explain one target date."""

    with account_connection(database_url, account_id) as conn:
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
    return {"weather": weather, "events": events}


def persist_recommendations(database_url: str, results: list[RecommendationResult]) -> None:
    """Upsert generated recommendation rows for one account."""

    if not results:
        return
    account_id = results[0].account_id
    with account_connection(database_url, account_id) as conn:
        for result in results:
            conn.execute(
                """
                INSERT INTO recommendations (
                    account_id,
                    location_id,
                    date,
                    category,
                    recommended_prep,
                    demand_p50,
                    demand_p_lower,
                    demand_p_upper,
                    service_quantile,
                    confidence,
                    risk_flag,
                    top_drivers,
                    model_version,
                    input_snapshot_id,
                    config_snapshot_id,
                    generated_at
                )
                VALUES (
                    %(account_id)s,
                    %(location_id)s,
                    %(date)s,
                    %(category)s,
                    %(recommended_prep)s,
                    %(demand_p50)s,
                    %(demand_p_lower)s,
                    %(demand_p_upper)s,
                    %(service_quantile)s,
                    %(confidence)s,
                    %(risk_flag)s,
                    %(top_drivers)s::jsonb,
                    %(model_version)s,
                    %(input_snapshot_id)s,
                    %(config_snapshot_id)s,
                    %(generated_at)s
                )
                ON CONFLICT (account_id, location_id, date, category, model_version)
                DO UPDATE SET
                    recommended_prep = EXCLUDED.recommended_prep,
                    demand_p50 = EXCLUDED.demand_p50,
                    demand_p_lower = EXCLUDED.demand_p_lower,
                    demand_p_upper = EXCLUDED.demand_p_upper,
                    service_quantile = EXCLUDED.service_quantile,
                    confidence = EXCLUDED.confidence,
                    risk_flag = EXCLUDED.risk_flag,
                    top_drivers = EXCLUDED.top_drivers,
                    input_snapshot_id = EXCLUDED.input_snapshot_id,
                    config_snapshot_id = EXCLUDED.config_snapshot_id,
                    generated_at = EXCLUDED.generated_at
                """,
                {
                    **result.__dict__,
                    "top_drivers": json.dumps(result.top_drivers),
                },
            )


def generate_and_store_recommendations(
    database_url: str,
    account_id: str,
    location_id: str,
    target_date: date,
) -> list[RecommendationResult]:
    """Build and persist recommendations for a target date."""

    frames = fetch_history_frames(database_url, account_id, location_id)
    results = build_recommendations(
        account_id=account_id,
        location_id=location_id,
        target_date=target_date,
        daily_metrics=frames["daily_metrics"],
        category_metrics=frames["daily_category_metrics"],
        weather=frames["weather"],
        events=frames["events"],
        economics=frames["category_economics"],
    )
    persist_recommendations(database_url, results)
    return results

