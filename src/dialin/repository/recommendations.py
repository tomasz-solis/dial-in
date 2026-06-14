"""Recommendation reads, persistence, and the generate-and-store workflow."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from time import perf_counter
from typing import Any

import pandas as pd

from dialin.db import account_connection, fetch_all, fetch_one
from dialin.engine import RecommendationResult, build_recommendations, result_to_record

logger = logging.getLogger(__name__)
RECOMMENDATION_HISTORY_DAYS = 365


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
            WHERE account_id = %s AND location_id = %s AND is_active = true
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
            WHERE account_id = %s
              AND location_id = %s
              AND date = %s
              AND is_active = true
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
    """Fetch active stored recommendation rows for one target date."""

    return fetch_active_recommendations_for_date(
        database_url,
        account_id,
        location_id,
        target_date,
    )


def fetch_active_recommendations_for_date(
    database_url: str,
    account_id: str,
    location_id: str,
    target_date: date,
) -> list[dict[str, Any]]:
    """Fetch active recommendation rows for one target date."""

    with account_connection(database_url, account_id) as conn:
        return fetch_all(
            conn,
            """
            SELECT *
            FROM recommendations
            WHERE account_id = %s
              AND location_id = %s
              AND date = %s
              AND is_active = true
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
            SELECT date, temp_forecast, rain_forecast, condition, forecast_made_at
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
    """Persist generated recommendation rows as append-only active advice."""

    insert_recommendation_set(database_url, results)


def insert_recommendation_set(
    database_url: str,
    results: list[RecommendationResult],
) -> list[str]:
    """Insert recommendation rows and supersede prior active rows for each category."""

    if not results:
        return []
    account_id = results[0].account_id
    inserted_ids: list[str] = []
    with account_connection(database_url, account_id) as conn:
        for result in results:
            prior_rows = fetch_all(
                conn,
                """
                SELECT recommendation_id
                FROM recommendations
                WHERE account_id = %s
                  AND location_id = %s
                  AND date = %s
                  AND category = %s
                  AND model_version = %s
                  AND is_active = true
                """,
                (
                    result.account_id,
                    result.location_id,
                    result.date,
                    result.category,
                    result.model_version,
                ),
            )
            prior_ids = [str(row["recommendation_id"]) for row in prior_rows]
            if prior_ids:
                supersede_active_recommendations(conn, prior_ids, result.generated_at)

            inserted = fetch_one(
                conn,
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
                    input_snapshot,
                    config_snapshot,
                    is_active,
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
                    %(input_snapshot)s::jsonb,
                    %(config_snapshot)s::jsonb,
                    true,
                    %(generated_at)s
                )
                RETURNING recommendation_id
                """,
                result_to_record(result),
            )
            if inserted is None:
                raise RuntimeError("Recommendation row was not inserted.")
            inserted_id = str(inserted["recommendation_id"])
            inserted_ids.append(inserted_id)
            if prior_ids:
                conn.execute(
                    """
                    UPDATE recommendations
                    SET superseded_by = %s
                    WHERE recommendation_id = ANY(%s)
                    """,
                    (inserted_id, prior_ids),
                )
    return inserted_ids


def supersede_active_recommendations(
    conn: Any,
    recommendation_ids: list[str],
    superseded_at: Any,
) -> None:
    """Mark active recommendation rows superseded before inserting replacements."""

    if not recommendation_ids:
        return
    conn.execute(
        """
        UPDATE recommendations
        SET is_active = false,
            superseded_at = %s
        WHERE recommendation_id = ANY(%s)
          AND is_active = true
        """,
        (superseded_at, recommendation_ids),
    )


def fetch_recommendation_build_payload(
    database_url: str,
    account_id: str,
    location_id: str,
    target_date: date,
    history_days: int = RECOMMENDATION_HISTORY_DAYS,
) -> dict[str, pd.DataFrame]:
    """Fetch the bounded data needed to build one target-date recommendation."""

    start_date = target_date - timedelta(days=history_days)
    with account_connection(database_url, account_id) as conn:
        tables = {
            "daily_metrics": fetch_all(
                conn,
                """
                SELECT date, is_open, drinks_sold, input_source, menu_version
                FROM daily_metrics
                WHERE account_id = %s
                  AND location_id = %s
                  AND date >= %s
                  AND date < %s
                ORDER BY date
                """,
                (account_id, location_id, start_date, target_date),
            ),
            "daily_category_metrics": fetch_all(
                conn,
                """
                SELECT date, category, sold, prepared, sold_out, input_source
                FROM daily_category_metrics
                WHERE account_id = %s
                  AND location_id = %s
                  AND date >= %s
                  AND date < %s
                ORDER BY date, category
                """,
                (account_id, location_id, start_date, target_date),
            ),
            "weather": fetch_all(
                conn,
                """
                SELECT date, temp_forecast, temp_actual, rain_forecast, rain_actual,
                       wind, condition, forecast_made_at, actual_observed_at
                FROM weather
                WHERE account_id = %s
                  AND location_id = %s
                  AND date = %s
                ORDER BY date
                """,
                (account_id, location_id, target_date),
            ),
            "events": fetch_all(
                conn,
                """
                SELECT date, event_name, event_type, impact_score, source, confidence
                FROM events
                WHERE account_id = %s
                  AND location_id = %s
                  AND date = %s
                ORDER BY date, impact_score DESC, event_name
                """,
                (account_id, location_id, target_date),
            ),
            "category_economics": fetch_all(
                conn,
                """
                SELECT account_id, location_id, category, retail_price, unit_cogs,
                       salvage_share_default, attached_drink_margin,
                       attach_and_balk_rate, service_quantile, effective_from,
                       effective_to, values_source
                FROM category_economics
                WHERE account_id = %s
                  AND location_id = %s
                  AND effective_from <= %s
                  AND (effective_to IS NULL OR effective_to > %s)
                ORDER BY category, effective_from
                """,
                (account_id, location_id, target_date, target_date),
            ),
        }
    return {name: pd.DataFrame(rows) for name, rows in tables.items()}


def generate_and_store_recommendations(
    database_url: str,
    account_id: str,
    location_id: str,
    target_date: date,
) -> list[RecommendationResult]:
    """Build and persist recommendations for a target date."""

    start = perf_counter()
    frames = fetch_recommendation_build_payload(database_url, account_id, location_id, target_date)
    fetch_elapsed = perf_counter() - start
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
    build_elapsed = perf_counter() - start - fetch_elapsed
    persist_recommendations(database_url, results)
    total_elapsed = perf_counter() - start
    logger.info(
        "generated %s recommendation rows for %s/%s target=%s fetch=%.3fs build=%.3fs total=%.3fs",
        len(results),
        account_id,
        location_id,
        target_date,
        fetch_elapsed,
        build_elapsed,
        total_elapsed,
    )
    return results
