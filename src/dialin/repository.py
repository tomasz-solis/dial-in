"""Account-scoped data access for the Dial In app and scripts."""

from __future__ import annotations

import json
import math
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from typing import Any, cast
from zoneinfo import ZoneInfo

import pandas as pd

from dialin.db import account_connection, fetch_all, fetch_one
from dialin.engine import RecommendationResult, build_recommendations, service_quantile
from dialin.pos_import import PosImportPreview

OVERRIDE_REASON_OPTIONS = (
    "weather felt wrong",
    "supplier issue",
    "large order",
    "owner judgement",
    "other",
)


def list_locations(database_url: str, account_id: str) -> list[dict[str, Any]]:
    """Return locations visible to one account."""

    with account_connection(database_url, account_id) as conn:
        return fetch_all(
            conn,
            """
            SELECT account_id, location_id, name, timezone, city, country
            FROM locations
            WHERE account_id = %s
            ORDER BY name
            """,
            (account_id,),
        )


def fetch_history_frames(
    database_url: str,
    account_id: str,
    location_id: str,
) -> dict[str, pd.DataFrame]:
    """Fetch observed account-scoped tables needed by the recommendation engine."""

    with account_connection(database_url, account_id) as conn:
        tables = {
            "daily_metrics": fetch_all(
                conn,
                """
                SELECT *
                FROM daily_metrics
                WHERE account_id = %s AND location_id = %s
                ORDER BY date
                """,
                (account_id, location_id),
            ),
            "daily_category_metrics": fetch_all(
                conn,
                """
                SELECT *
                FROM daily_category_metrics
                WHERE account_id = %s AND location_id = %s
                ORDER BY date, category
                """,
                (account_id, location_id),
            ),
            "weather": fetch_all(
                conn,
                """
                SELECT *
                FROM weather
                WHERE account_id = %s AND location_id = %s
                ORDER BY date
                """,
                (account_id, location_id),
            ),
            "events": fetch_all(
                conn,
                """
                SELECT *
                FROM events
                WHERE account_id = %s AND location_id = %s
                ORDER BY date
                """,
                (account_id, location_id),
            ),
            "category_economics": fetch_all(
                conn,
                """
                SELECT *
                FROM category_economics
                WHERE account_id = %s AND location_id = %s
                ORDER BY category, effective_from
                """,
                (account_id, location_id),
            ),
            "pos_daily_sales": fetch_all(
                conn,
                """
                SELECT *
                FROM pos_daily_sales
                WHERE account_id = %s AND location_id = %s
                ORDER BY date, category
                """,
                (account_id, location_id),
            ),
        }
    return {name: pd.DataFrame(rows) for name, rows in tables.items()}


def latest_business_date(database_url: str, account_id: str, location_id: str) -> date | None:
    """Return the latest open daily metric date for an account location."""

    with account_connection(database_url, account_id) as conn:
        row = fetch_one(
            conn,
            """
            SELECT max(date) AS latest_date
            FROM daily_metrics
            WHERE account_id = %s AND location_id = %s AND is_open = true
            """,
            (account_id, location_id),
        )
    if row is None or row["latest_date"] is None:
        return None
    return cast(date, row["latest_date"])


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


def fetch_location_hours_plan(
    database_url: str,
    account_id: str,
    location_id: str,
    as_of: date,
) -> list[dict[str, Any]]:
    """Return the active weekly opening-hours plan for one location."""

    with account_connection(database_url, account_id) as conn:
        location = fetch_one(
            conn,
            """
            SELECT open_days
            FROM locations
            WHERE account_id = %s AND location_id = %s
            """,
            (account_id, location_id),
        )
        rows = fetch_all(
            conn,
            """
            SELECT DISTINCT ON (day_of_week)
                   day_of_week, is_open, open_time, close_time,
                   effective_from, effective_to, source
            FROM location_hours
            WHERE account_id = %s
              AND location_id = %s
              AND effective_from <= %s
              AND (effective_to IS NULL OR effective_to > %s)
            ORDER BY day_of_week, effective_from DESC
            """,
            (account_id, location_id, as_of, as_of),
        )

    open_days = [] if location is None else list(location.get("open_days") or [])
    rows_by_day = {int(row["day_of_week"]): row for row in rows}
    plan: list[dict[str, Any]] = []
    for day_of_week in range(7):
        if day_of_week in rows_by_day:
            plan.append(rows_by_day[day_of_week])
            continue
        sample_date = as_of + timedelta(days=(day_of_week - as_of.weekday()) % 7)
        plan.append(effective_location_hours([], sample_date, open_days=open_days))
    return sorted(plan, key=lambda row: int(row["day_of_week"]))


def upsert_location_hours(
    database_url: str,
    account_id: str,
    location_id: str,
    day_of_week: int,
    is_open: bool,
    open_time: time | None,
    close_time: time | None,
    effective_from: date,
    source: str = "owner_confirmed",
) -> None:
    """Insert or update one effective-dated opening-hours row."""

    if day_of_week < 0 or day_of_week > 6:
        raise ValueError("day_of_week must be between 0 and 6.")
    if source not in {"demo_seed", "owner_confirmed", "corrected"}:
        raise ValueError("source must be demo_seed, owner_confirmed, or corrected.")
    if is_open and (open_time is None or close_time is None):
        raise ValueError("Open days need both opening and closing times.")
    if not is_open:
        open_time = None
        close_time = None
    if open_time is not None and close_time is not None and close_time <= open_time:
        raise ValueError("Closing time must be after opening time.")

    with account_connection(database_url, account_id) as conn:
        next_row = fetch_one(
            conn,
            """
            SELECT min(effective_from) AS next_effective_from
            FROM location_hours
            WHERE account_id = %s
              AND location_id = %s
              AND day_of_week = %s
              AND effective_from > %s
            """,
            (account_id, location_id, day_of_week, effective_from),
        )
        next_effective_from = (
            None if next_row is None else next_row.get("next_effective_from")
        )
        conn.execute(
            """
            UPDATE location_hours
            SET effective_to = %s
            WHERE account_id = %s
              AND location_id = %s
              AND day_of_week = %s
              AND effective_from < %s
              AND (effective_to IS NULL OR effective_to > %s)
            """,
            (
                effective_from,
                account_id,
                location_id,
                day_of_week,
                effective_from,
                effective_from,
            ),
        )
        conn.execute(
            """
            INSERT INTO location_hours (
                account_id,
                location_id,
                day_of_week,
                is_open,
                open_time,
                close_time,
                effective_from,
                effective_to,
                source
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (account_id, location_id, day_of_week, effective_from)
            DO UPDATE SET
                is_open = EXCLUDED.is_open,
                open_time = EXCLUDED.open_time,
                close_time = EXCLUDED.close_time,
                effective_to = EXCLUDED.effective_to,
                source = EXCLUDED.source
            """,
            (
                account_id,
                location_id,
                day_of_week,
                is_open,
                open_time,
                close_time,
                effective_from,
                next_effective_from,
                source,
            ),
        )


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


def fetch_intraday_demo(
    database_url: str,
    account_id: str,
    location_id: str,
    business_date: date,
) -> dict[str, Any]:
    """Fetch a demo intraday service view for one business date."""

    weekday = business_date.weekday()
    with account_connection(database_url, account_id) as conn:
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
            (account_id, location_id, weekday, business_date, business_date),
        )
        daily_row = fetch_one(
            conn,
            """
            SELECT date, is_open, drinks_sold, input_source
            FROM daily_metrics
            WHERE account_id = %s AND location_id = %s AND date = %s
            """,
            (account_id, location_id, business_date),
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
            (account_id, location_id, business_date),
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
            (account_id, location_id, business_date),
        )

    open_days = [] if location is None else list(location.get("open_days") or [])
    hours = effective_location_hours(hours_rows, business_date, open_days)
    expected_drinks, expected_source = expected_intraday_drinks(
        daily_row,
        history_rows,
        business_date,
    )
    return {
        "business_date": business_date,
        "hours": hours,
        "expected_drinks": expected_drinks,
        "expected_source": expected_source,
        "curve": build_intraday_pressure_curve(
            hours.get("open_time"),
            hours.get("close_time"),
            expected_drinks,
        ),
        "sellouts": sellouts,
    }


def effective_location_hours(
    rows: list[dict[str, Any]],
    business_date: date,
    open_days: list[int] | None = None,
) -> dict[str, Any]:
    """Return the active opening-hours row or a conservative location fallback."""

    active_rows = [
        row
        for row in rows
        if int(row["day_of_week"]) == business_date.weekday()
        and _as_date(row["effective_from"]) <= business_date
        and (row.get("effective_to") is None or _as_date(row["effective_to"]) > business_date)
    ]
    if active_rows:
        row = sorted(active_rows, key=lambda item: _as_date(item["effective_from"]))[-1]
        return {
            "day_of_week": business_date.weekday(),
            "is_open": bool(row["is_open"]),
            "open_time": row.get("open_time"),
            "close_time": row.get("close_time"),
            "source": str(row.get("source") or "demo_seed"),
        }

    fallback_open = business_date.weekday() in set(open_days or [])
    return {
        "day_of_week": business_date.weekday(),
        "is_open": fallback_open,
        "open_time": time(8, 0) if fallback_open else None,
        "close_time": time(16, 0) if fallback_open else None,
        "source": "location_open_days",
    }


def expected_intraday_drinks(
    daily_row: dict[str, Any] | None,
    history_rows: list[dict[str, Any]],
    business_date: date,
) -> tuple[int, str]:
    """Return observed or trailing expected drinks for the intraday demo."""

    if (
        daily_row is not None
        and daily_row.get("is_open") is True
        and daily_row.get("input_source") != "imputed"
        and daily_row.get("drinks_sold") is not None
    ):
        return max(0, int(daily_row["drinks_sold"])), "observed closeout"

    same_weekday = [
        int(row["drinks_sold"])
        for row in history_rows
        if _as_date(row["date"]).weekday() == business_date.weekday()
    ][:8]
    if same_weekday:
        return round(sum(same_weekday) / len(same_weekday)), "same-weekday history"

    recent = [int(row["drinks_sold"]) for row in history_rows[:14]]
    if recent:
        return round(sum(recent) / len(recent)), "recent history"

    return 100, "demo fallback"


def build_intraday_pressure_curve(
    open_time: Any,
    close_time: Any,
    expected_drinks: int,
) -> list[dict[str, Any]]:
    """Build a synthetic half-hour service-pressure curve for the demo panel."""

    start = _minutes_from_time(open_time)
    end = _minutes_from_time(close_time)
    if start is None or end is None or end <= start:
        return []

    bucket_minutes = 30
    bucket_count = max(1, math.ceil((end - start) / bucket_minutes))
    buckets: list[tuple[int, int, float]] = []
    for index in range(bucket_count):
        bucket_start = start + index * bucket_minutes
        bucket_end = min(bucket_start + bucket_minutes, end)
        center = (bucket_start + bucket_end) / 2
        progress = (center - start) / max(end - start, 1)
        buckets.append((bucket_start, bucket_end, _daypart_weight(progress)))

    total_weight = sum(weight for _bucket_start, _bucket_end, weight in buckets)
    mean_weight = total_weight / len(buckets)
    expected = max(float(expected_drinks), 0.0)
    return [
        {
            "time": _format_minutes(bucket_start),
            "expected_drinks": round(expected * weight / total_weight, 1),
            "pressure_index": round(weight / mean_weight * 100),
        }
        for bucket_start, _bucket_end, weight in buckets
    ]


def fetch_category_economics(
    database_url: str,
    account_id: str,
    location_id: str,
    as_of: date,
) -> list[dict[str, Any]]:
    """Fetch category economics rows effective on one business date."""

    with account_connection(database_url, account_id) as conn:
        return fetch_all(
            conn,
            """
            SELECT *
            FROM category_economics
            WHERE account_id = %s
              AND location_id = %s
              AND effective_from <= %s
              AND (effective_to IS NULL OR effective_to > %s)
            ORDER BY category
            """,
            (account_id, location_id, as_of, as_of),
        )


def economics_service_quantile(
    retail_price: float,
    unit_cogs: float,
    salvage_share_default: float,
    attached_drink_margin: float,
    attach_and_balk_rate: float,
) -> float:
    """Compute the newsvendor service quantile from category economics."""

    if retail_price < 0:
        raise ValueError("Retail price must be non-negative.")
    if unit_cogs <= 0:
        raise ValueError("Unit COGS must be positive.")
    if not 0 <= salvage_share_default < 1:
        raise ValueError("Salvage share must be at least 0 and below 1.")
    if attached_drink_margin < 0:
        raise ValueError("Attached drink margin must be non-negative.")
    if not 0 <= attach_and_balk_rate <= 1:
        raise ValueError("Attach-and-balk rate must be between 0 and 1.")

    under_cost = retail_price - unit_cogs + attach_and_balk_rate * attached_drink_margin
    over_cost = unit_cogs * (1 - salvage_share_default)
    return service_quantile(under_cost, over_cost)


def upsert_category_economics(
    database_url: str,
    account_id: str,
    location_id: str,
    category: str,
    effective_from: date,
    retail_price: float,
    unit_cogs: float,
    salvage_share_default: float,
    attached_drink_margin: float,
    attach_and_balk_rate: float,
    values_source: str = "owner_confirmed",
) -> float:
    """Insert or update one effective-dated category economics row."""

    if values_source not in {"default", "owner_confirmed", "corrected"}:
        raise ValueError("values_source must be default, owner_confirmed, or corrected.")
    quantile = economics_service_quantile(
        retail_price=retail_price,
        unit_cogs=unit_cogs,
        salvage_share_default=salvage_share_default,
        attached_drink_margin=attached_drink_margin,
        attach_and_balk_rate=attach_and_balk_rate,
    )
    rounded_quantile = round(quantile, 4)
    with account_connection(database_url, account_id) as conn:
        next_row = fetch_one(
            conn,
            """
            SELECT min(effective_from) AS next_effective_from
            FROM category_economics
            WHERE account_id = %s
              AND location_id = %s
              AND category = %s
              AND effective_from > %s
            """,
            (account_id, location_id, category, effective_from),
        )
        next_effective_from = (
            None if next_row is None else next_row.get("next_effective_from")
        )
        conn.execute(
            """
            UPDATE category_economics
            SET effective_to = %s
            WHERE account_id = %s
              AND location_id = %s
              AND category = %s
              AND effective_from < %s
              AND (effective_to IS NULL OR effective_to > %s)
            """,
            (effective_from, account_id, location_id, category, effective_from, effective_from),
        )
        conn.execute(
            """
            INSERT INTO category_economics (
                account_id,
                location_id,
                category,
                retail_price,
                unit_cogs,
                salvage_share_default,
                attached_drink_margin,
                attach_and_balk_rate,
                service_quantile,
                values_source,
                effective_from,
                effective_to
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (account_id, location_id, category, effective_from)
            DO UPDATE SET
                retail_price = EXCLUDED.retail_price,
                unit_cogs = EXCLUDED.unit_cogs,
                salvage_share_default = EXCLUDED.salvage_share_default,
                attached_drink_margin = EXCLUDED.attached_drink_margin,
                attach_and_balk_rate = EXCLUDED.attach_and_balk_rate,
                service_quantile = EXCLUDED.service_quantile,
                values_source = EXCLUDED.values_source,
                effective_to = EXCLUDED.effective_to
            """,
            (
                account_id,
                location_id,
                category,
                retail_price,
                unit_cogs,
                salvage_share_default,
                attached_drink_margin,
                attach_and_balk_rate,
                rounded_quantile,
                values_source,
                effective_from,
                next_effective_from,
            ),
        )
    return rounded_quantile


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


def upsert_closeout(
    database_url: str,
    account_id: str,
    location_id: str,
    business_date: date,
    timezone_name: str,
    drinks_sold: int,
    sweet_sold: int,
    savory_sold: int,
    sweet_prepared: int,
    savory_prepared: int,
    sweet_sold_out: bool | None = None,
    savory_sold_out: bool | None = None,
    sweet_time_last_sale: time | None = None,
    savory_time_last_sale: time | None = None,
    sweet_override_reason: str | None = None,
    savory_override_reason: str | None = None,
    menu_version: str = "v1",
    corrected_by: str = "app",
) -> None:
    """Write the manual v1 daily closeout numbers after validation."""

    if any(
        value < 0
        for value in (drinks_sold, sweet_sold, savory_sold, sweet_prepared, savory_prepared)
    ):
        raise ValueError("Counts must be non-negative.")
    if sweet_sold > sweet_prepared:
        raise ValueError("Sweet sold cannot exceed sweet prepared.")
    if savory_sold > savory_prepared:
        raise ValueError("Savory sold cannot exceed savory prepared.")
    normalized_menu_version = normalize_menu_version(menu_version)

    recorded_at = datetime.now(UTC)
    with account_connection(database_url, account_id) as conn:
        daily_updates = {
            "timezone": timezone_name,
            "is_open": True,
            "drinks_sold": drinks_sold,
            "menu_version": normalized_menu_version,
        }
        existing_daily = _fetch_daily_metric(conn, account_id, location_id, business_date)
        daily_input_source = correction_input_source(existing_daily, daily_updates)
        _audit_daily_changes(
            conn=conn,
            account_id=account_id,
            location_id=location_id,
            business_date=business_date,
            existing=existing_daily,
            updates={**daily_updates, "input_source": daily_input_source},
            corrected_by=corrected_by,
            reason="closeout update",
        )
        conn.execute(
            """
            INSERT INTO daily_metrics (
                account_id, location_id, date, timezone, is_open, drinks_sold,
                input_source, menu_version, recorded_at
            )
            VALUES (%s, %s, %s, %s, true, %s, %s, %s, %s)
            ON CONFLICT (account_id, location_id, date)
            DO UPDATE SET
                timezone = EXCLUDED.timezone,
                is_open = EXCLUDED.is_open,
                drinks_sold = EXCLUDED.drinks_sold,
                input_source = EXCLUDED.input_source,
                menu_version = EXCLUDED.menu_version,
                recorded_at = EXCLUDED.recorded_at
            """,
            (
                account_id,
                location_id,
                business_date,
                timezone_name,
                drinks_sold,
                daily_input_source,
                normalized_menu_version,
                recorded_at,
            ),
        )
        for category, sold, prepared, explicit_sold_out, time_last_sale in (
            (
                "sweet",
                sweet_sold,
                sweet_prepared,
                sweet_sold_out,
                sweet_time_last_sale,
            ),
            (
                "savory",
                savory_sold,
                savory_prepared,
                savory_sold_out,
                savory_time_last_sale,
            ),
        ):
            sold_out = explicit_sold_out if explicit_sold_out is not None else sold >= prepared - 1
            if time_last_sale is not None:
                sold_out = True
            stockout_detected_by = "manual" if time_last_sale is not None else "inferred_cap"
            stockout_timestamp = _local_stockout_timestamp(
                business_date,
                time_last_sale,
                timezone_name,
            )
            category_updates = {
                "sold": sold,
                "prepared": prepared,
                "sold_out": sold_out,
                "stockout_detected_by": stockout_detected_by,
                "time_last_sale": stockout_timestamp,
            }
            existing_category = _fetch_category_metric(
                conn,
                account_id,
                location_id,
                business_date,
                category,
            )
            category_input_source = correction_input_source(existing_category, category_updates)
            _audit_category_changes(
                conn=conn,
                account_id=account_id,
                location_id=location_id,
                business_date=business_date,
                category=category,
                existing=existing_category,
                updates={**category_updates, "input_source": category_input_source},
                corrected_by=corrected_by,
                reason="closeout update",
            )
            conn.execute(
                """
                INSERT INTO daily_category_metrics (
                    account_id, location_id, date, category, sold, prepared, sold_out,
                    stockout_detected_by, time_last_sale, input_source
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (account_id, location_id, date, category)
                DO UPDATE SET
                    sold = EXCLUDED.sold,
                    prepared = EXCLUDED.prepared,
                    sold_out = EXCLUDED.sold_out,
                    stockout_detected_by = EXCLUDED.stockout_detected_by,
                    time_last_sale = EXCLUDED.time_last_sale,
                    input_source = EXCLUDED.input_source
                """,
                (
                    account_id,
                    location_id,
                    business_date,
                    category,
                    sold,
                    prepared,
                    sold_out,
                    stockout_detected_by,
                    stockout_timestamp,
                    category_input_source,
                ),
            )
            reason = (
                normalize_override_reason(sweet_override_reason)
                if category == "sweet"
                else normalize_override_reason(savory_override_reason)
            )
            _update_recommendation_outcome(
                conn=conn,
                account_id=account_id,
                location_id=location_id,
                business_date=business_date,
                category=category,
                prepared=prepared,
                override_reason=reason,
            )


def mark_closed_day(
    database_url: str,
    account_id: str,
    location_id: str,
    business_date: date,
    timezone_name: str,
    menu_version: str = "v1",
    corrected_by: str = "app",
    reason: str = "closed day",
) -> None:
    """Mark a business date as closed and remove category demand rows."""

    recorded_at = datetime.now(UTC)
    normalized_menu_version = normalize_menu_version(menu_version)
    with account_connection(database_url, account_id) as conn:
        daily_updates = {
            "timezone": timezone_name,
            "is_open": False,
            "drinks_sold": None,
            "menu_version": normalized_menu_version,
        }
        existing_daily = _fetch_daily_metric(conn, account_id, location_id, business_date)
        daily_input_source = correction_input_source(
            existing_daily,
            daily_updates,
            default="corrected",
        )
        _audit_daily_changes(
            conn=conn,
            account_id=account_id,
            location_id=location_id,
            business_date=business_date,
            existing=existing_daily,
            updates={**daily_updates, "input_source": daily_input_source},
            corrected_by=corrected_by,
            reason=reason,
        )
        _audit_category_removals(
            conn=conn,
            account_id=account_id,
            location_id=location_id,
            business_date=business_date,
            corrected_by=corrected_by,
            reason=reason,
        )
        conn.execute(
            """
            INSERT INTO daily_metrics (
                account_id, location_id, date, timezone, is_open, drinks_sold,
                input_source, menu_version, recorded_at
            )
            VALUES (%s, %s, %s, %s, false, NULL, %s, %s, %s)
            ON CONFLICT (account_id, location_id, date)
            DO UPDATE SET
                timezone = EXCLUDED.timezone,
                is_open = EXCLUDED.is_open,
                drinks_sold = EXCLUDED.drinks_sold,
                input_source = EXCLUDED.input_source,
                menu_version = EXCLUDED.menu_version,
                recorded_at = EXCLUDED.recorded_at
            """,
            (
                account_id,
                location_id,
                business_date,
                timezone_name,
                daily_input_source,
                normalized_menu_version,
                recorded_at,
            ),
        )
        conn.execute(
            """
            DELETE FROM daily_category_metrics
            WHERE account_id = %s AND location_id = %s AND date = %s
            """,
            (account_id, location_id, business_date),
        )
        _clear_recommendation_outcomes(conn, account_id, location_id, business_date)


def mark_missing_input(
    database_url: str,
    account_id: str,
    location_id: str,
    business_date: date,
    timezone_name: str,
    menu_version: str = "v1",
    corrected_by: str = "app",
    reason: str = "missing closeout input",
) -> None:
    """Record a skipped closeout without creating fake demand rows."""

    recorded_at = datetime.now(UTC)
    normalized_menu_version = normalize_menu_version(menu_version)
    with account_connection(database_url, account_id) as conn:
        daily_updates = {
            "timezone": timezone_name,
            "is_open": True,
            "drinks_sold": None,
            "menu_version": normalized_menu_version,
            "input_source": "imputed",
        }
        existing_daily = _fetch_daily_metric(conn, account_id, location_id, business_date)
        if existing_daily is None:
            _append_correction(
                conn=conn,
                account_id=account_id,
                location_id=location_id,
                business_date=business_date,
                category=None,
                field_name="input_source",
                old_value=None,
                new_value="imputed",
                corrected_by=corrected_by,
                reason=reason,
            )
        _audit_daily_changes(
            conn=conn,
            account_id=account_id,
            location_id=location_id,
            business_date=business_date,
            existing=existing_daily,
            updates=daily_updates,
            corrected_by=corrected_by,
            reason=reason,
        )
        _audit_category_removals(
            conn=conn,
            account_id=account_id,
            location_id=location_id,
            business_date=business_date,
            corrected_by=corrected_by,
            reason=reason,
        )
        conn.execute(
            """
            INSERT INTO daily_metrics (
                account_id, location_id, date, timezone, is_open, drinks_sold,
                input_source, menu_version, recorded_at
            )
            VALUES (%s, %s, %s, %s, true, NULL, 'imputed', %s, %s)
            ON CONFLICT (account_id, location_id, date)
            DO UPDATE SET
                timezone = EXCLUDED.timezone,
                is_open = EXCLUDED.is_open,
                drinks_sold = EXCLUDED.drinks_sold,
                input_source = EXCLUDED.input_source,
                menu_version = EXCLUDED.menu_version,
                recorded_at = EXCLUDED.recorded_at
            """,
            (
                account_id,
                location_id,
                business_date,
                timezone_name,
                normalized_menu_version,
                recorded_at,
            ),
        )
        conn.execute(
            """
            DELETE FROM daily_category_metrics
            WHERE account_id = %s AND location_id = %s AND date = %s
            """,
            (account_id, location_id, business_date),
        )
        _clear_recommendation_outcomes(conn, account_id, location_id, business_date)


def apply_pos_import(
    database_url: str,
    account_id: str,
    location_id: str,
    filename: str,
    created_by: str,
    timezone_name: str,
    preview: PosImportPreview,
    mapping: dict[str, Any],
) -> dict[str, Any]:
    """Apply a previewed POS import into tenant-scoped rollup tables."""

    if not preview.can_apply:
        raise ValueError("Import preview is not applyable.")
    if preview.date_start is None or preview.date_end is None:
        raise ValueError("Import preview has no date range.")

    applied_at = datetime.now(UTC)
    mapping_json = json.dumps(mapping, sort_keys=True)
    with account_connection(database_url, account_id) as conn:
        run = fetch_one(
            conn,
            """
            INSERT INTO pos_import_runs (
                account_id,
                location_id,
                filename,
                created_by,
                date_start,
                date_end,
                rows_read,
                rows_imported,
                rows_rejected,
                timestamp_coverage,
                mapping_snapshot,
                created_at,
                applied_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)
            RETURNING import_run_id
            """,
            (
                account_id,
                location_id,
                filename,
                created_by,
                preview.date_start,
                preview.date_end,
                preview.rows_read,
                preview.rows_imported,
                preview.rows_rejected,
                preview.timestamp_coverage,
                mapping_json,
                applied_at,
                applied_at,
            ),
        )
        if run is None:
            raise RuntimeError("POS import run was not created.")
        import_run_id = str(run["import_run_id"])

        conn.execute(
            """
            DELETE FROM pos_daily_sales
            WHERE account_id = %s
              AND location_id = %s
              AND date BETWEEN %s AND %s
            """,
            (account_id, location_id, preview.date_start, preview.date_end),
        )
        for rollup in preview.rollups:
            conn.execute(
                """
                INSERT INTO pos_daily_sales (
                    account_id,
                    location_id,
                    date,
                    category,
                    units_sold,
                    first_sale_at,
                    last_sale_at,
                    import_run_id,
                    imported_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    account_id,
                    location_id,
                    rollup.business_date,
                    rollup.category,
                    rollup.units_sold,
                    rollup.first_sale_at,
                    rollup.last_sale_at,
                    import_run_id,
                    applied_at,
                ),
            )
            if rollup.category == "drinks":
                _upsert_imported_drinks(
                    conn=conn,
                    account_id=account_id,
                    location_id=location_id,
                    business_date=rollup.business_date,
                    timezone_name=timezone_name,
                    drinks_sold=rollup.units_sold,
                    recorded_at=applied_at,
                )

        for error in preview.errors:
            conn.execute(
                """
                INSERT INTO pos_import_errors (
                    import_run_id,
                    account_id,
                    location_id,
                    row_number,
                    reason,
                    raw_row
                )
                VALUES (%s, %s, %s, %s, %s, %s::jsonb)
                """,
                (
                    import_run_id,
                    account_id,
                    location_id,
                    error.row_number,
                    error.reason,
                    json.dumps(error.raw_row, sort_keys=True),
                ),
            )

    return {
        "import_run_id": import_run_id,
        "date_start": preview.date_start,
        "date_end": preview.date_end,
        "rows_imported": preview.rows_imported,
        "rows_rejected": preview.rows_rejected,
    }


def fetch_recent_pos_import_runs(
    database_url: str,
    account_id: str,
    location_id: str,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Fetch recent POS import summaries for one account location."""

    with account_connection(database_url, account_id) as conn:
        return fetch_all(
            conn,
            """
            SELECT filename, date_start, date_end, rows_read, rows_imported,
                   rows_rejected, timestamp_coverage, created_by, applied_at
            FROM pos_import_runs
            WHERE account_id = %s AND location_id = %s
            ORDER BY applied_at DESC
            LIMIT %s
            """,
            (account_id, location_id, limit),
        )


def fetch_data_corrections(
    database_url: str,
    account_id: str,
    location_id: str,
    limit: int = 25,
) -> list[dict[str, Any]]:
    """Fetch recent correction audit rows for one account location."""

    with account_connection(database_url, account_id) as conn:
        return fetch_all(
            conn,
            """
            SELECT date, category, field_name, old_value, new_value,
                   corrected_by, corrected_at, reason
            FROM data_corrections
            WHERE account_id = %s AND location_id = %s
            ORDER BY corrected_at DESC, date DESC
            LIMIT %s
            """,
            (account_id, location_id, limit),
        )


def fetch_recommendation_outcomes(
    database_url: str,
    account_id: str,
    location_id: str,
) -> list[dict[str, Any]]:
    """Fetch recommendation rows joined with observed closeouts, with quantiles.

    Unlike :func:`scorecard`, this keeps the stored demand quantiles, service
    quantile, and confidence label so calibration coverage and pinball loss can
    be computed against the model's own stated distribution.
    """

    with account_connection(database_url, account_id) as conn:
        return fetch_all(
            conn,
            """
            SELECT
                r.date,
                r.category,
                r.recommended_prep,
                r.demand_p50,
                r.demand_p_lower,
                r.demand_p_upper,
                r.service_quantile,
                r.confidence,
                r.adhered,
                c.sold,
                c.prepared AS actual_prepared,
                c.sold_out
            FROM recommendations r
            JOIN daily_category_metrics c
              ON c.account_id = r.account_id
             AND c.location_id = r.location_id
             AND c.date = r.date
             AND c.category = r.category
            WHERE r.account_id = %s AND r.location_id = %s
              AND c.input_source <> 'imputed'
            ORDER BY r.date, r.category
            """,
            (account_id, location_id),
        )


def scorecard(database_url: str, account_id: str, location_id: str) -> dict[str, Any]:
    """Return an honest observed-only replay comparison for the app."""

    with account_connection(database_url, account_id) as conn:
        rows = fetch_all(
            conn,
            """
            SELECT
                r.date,
                r.category,
                r.recommended_prep,
                r.prepared AS recommendation_prepared,
                r.adhered,
                r.override_delta,
                r.override_reason,
                c.sold,
                c.prepared AS actual_prepared,
                c.sold_out
            FROM recommendations r
            JOIN daily_category_metrics c
              ON c.account_id = r.account_id
             AND c.location_id = r.location_id
             AND c.date = r.date
             AND c.category = r.category
            WHERE r.account_id = %s AND r.location_id = %s
              AND c.input_source <> 'imputed'
            ORDER BY r.date, r.category
            """,
            (account_id, location_id),
        )
    if not rows:
        return {
            "rows": [],
            "actual_waste": 0,
            "dialin_waste_proxy": 0,
            "actual_sellouts": 0,
            "dialin_short_proxy": 0,
            "attributed_rows": 0,
            "adhered_rows": 0,
            "overridden_rows": 0,
        }

    actual_waste = sum(max(int(row["actual_prepared"]) - int(row["sold"]), 0) for row in rows)
    dialin_waste_proxy = sum(
        max(int(row["recommended_prep"]) - int(row["sold"]), 0) for row in rows
    )
    actual_sellouts = sum(1 for row in rows if row["sold_out"])
    dialin_short_proxy = sum(1 for row in rows if int(row["recommended_prep"]) < int(row["sold"]))
    attributed_rows = sum(1 for row in rows if row["adhered"] is not None)
    adhered_rows = sum(1 for row in rows if row["adhered"] is True)
    overridden_rows = sum(1 for row in rows if row["adhered"] is False)
    return {
        "rows": rows,
        "actual_waste": actual_waste,
        "dialin_waste_proxy": dialin_waste_proxy,
        "actual_sellouts": actual_sellouts,
        "dialin_short_proxy": dialin_short_proxy,
        "attributed_rows": attributed_rows,
        "adhered_rows": adhered_rows,
        "overridden_rows": overridden_rows,
    }


def recommendation_adhered(prepared: int, recommended_prep: int) -> bool:
    """Return whether actual prep stayed within the recommendation tolerance."""

    tolerance = max(2.0, recommended_prep * 0.10)
    return abs(prepared - recommended_prep) <= tolerance


def normalize_override_reason(reason: str | None) -> str | None:
    """Return a stored override reason or None for blank/default input."""

    if reason is None:
        return None
    stripped = reason.strip()
    if not stripped or stripped == "No reason":
        return None
    return stripped


def normalize_menu_version(menu_version: str | None) -> str:
    """Return a clean menu version label for closeout rows."""

    if menu_version is None:
        return "v1"
    stripped = menu_version.strip()
    return stripped or "v1"


def correction_changes(
    existing: dict[str, Any] | None,
    updates: dict[str, Any],
) -> list[tuple[str, Any, Any]]:
    """Return changed fields between an existing row and proposed updates."""

    if existing is None:
        return []
    changes: list[tuple[str, Any, Any]] = []
    for field_name, new_value in updates.items():
        old_value = existing.get(field_name)
        if old_value != new_value:
            changes.append((field_name, old_value, new_value))
    return changes


def correction_input_source(
    existing: dict[str, Any] | None,
    updates: dict[str, Any],
    default: str = "confirmed",
) -> str:
    """Return the canonical input source for an upserted operational row."""

    if existing is None:
        return default
    if correction_changes(existing, updates):
        return "corrected"
    return str(existing.get("input_source") or default)


def _update_recommendation_outcome(
    conn: Any,
    account_id: str,
    location_id: str,
    business_date: date,
    category: str,
    prepared: int,
    override_reason: str | None,
) -> None:
    """Populate attribution fields for a recommendation after the target day closes."""

    rows = fetch_all(
        conn,
        """
        SELECT recommendation_id, recommended_prep
        FROM recommendations
        WHERE account_id = %s
          AND location_id = %s
          AND date = %s
          AND category = %s
        """,
        (account_id, location_id, business_date, category),
    )
    for row in rows:
        recommended_prep = int(row["recommended_prep"])
        adhered = recommendation_adhered(prepared, recommended_prep)
        stored_reason = None if adhered else override_reason
        conn.execute(
            """
            UPDATE recommendations
            SET prepared = %s,
                adhered = %s,
                override_delta = %s,
                override_reason = %s
            WHERE recommendation_id = %s
            """,
            (
                prepared,
                adhered,
                prepared - recommended_prep,
                stored_reason,
                row["recommendation_id"],
            ),
        )


def _clear_recommendation_outcomes(
    conn: Any,
    account_id: str,
    location_id: str,
    business_date: date,
) -> None:
    """Remove stale recommendation attribution when a target date is closed."""

    conn.execute(
        """
        UPDATE recommendations
        SET prepared = NULL,
            adhered = NULL,
            override_delta = NULL,
            override_reason = NULL
        WHERE account_id = %s
          AND location_id = %s
          AND date = %s
        """,
        (account_id, location_id, business_date),
    )


def _upsert_imported_drinks(
    conn: Any,
    account_id: str,
    location_id: str,
    business_date: date,
    timezone_name: str,
    drinks_sold: int,
    recorded_at: datetime,
) -> None:
    """Upsert imported POS drinks into the daily traffic history."""

    conn.execute(
        """
        INSERT INTO daily_metrics (
            account_id,
            location_id,
            date,
            timezone,
            is_open,
            drinks_sold,
            input_source,
            menu_version,
            recorded_at
        )
        VALUES (%s, %s, %s, %s, true, %s, 'imported', 'v1', %s)
        ON CONFLICT (account_id, location_id, date)
        DO UPDATE SET
            timezone = EXCLUDED.timezone,
            is_open = true,
            drinks_sold = EXCLUDED.drinks_sold,
            input_source = EXCLUDED.input_source,
            menu_version = daily_metrics.menu_version,
            recorded_at = EXCLUDED.recorded_at
        """,
        (
            account_id,
            location_id,
            business_date,
            timezone_name,
            drinks_sold,
            recorded_at,
        ),
    )


def _local_stockout_timestamp(
    business_date: date,
    sale_time: time | None,
    timezone_name: str,
) -> datetime | None:
    """Return a timezone-aware stockout timestamp from a local closeout time."""

    if sale_time is None:
        return None
    try:
        timezone: tzinfo = ZoneInfo(timezone_name)
    except Exception:
        timezone = UTC
    return datetime.combine(business_date, sale_time, tzinfo=timezone)


def _fetch_daily_metric(
    conn: Any,
    account_id: str,
    location_id: str,
    business_date: date,
) -> dict[str, Any] | None:
    """Fetch one daily metric row for correction comparison."""

    return fetch_one(
        conn,
        """
        SELECT timezone, is_open, drinks_sold, input_source, menu_version
        FROM daily_metrics
        WHERE account_id = %s AND location_id = %s AND date = %s
        """,
        (account_id, location_id, business_date),
    )


def _fetch_category_metric(
    conn: Any,
    account_id: str,
    location_id: str,
    business_date: date,
    category: str,
) -> dict[str, Any] | None:
    """Fetch one category metric row for correction comparison."""

    return fetch_one(
        conn,
        """
        SELECT sold, prepared, sold_out, stockout_detected_by, time_last_sale, input_source
        FROM daily_category_metrics
        WHERE account_id = %s
          AND location_id = %s
          AND date = %s
          AND category = %s
        """,
        (account_id, location_id, business_date, category),
    )


def _audit_category_removals(
    conn: Any,
    account_id: str,
    location_id: str,
    business_date: date,
    corrected_by: str,
    reason: str,
) -> None:
    """Append audit rows before removing category metrics for one date."""

    rows = fetch_all(
        conn,
        """
        SELECT category, sold, prepared, sold_out, stockout_detected_by, input_source
        FROM daily_category_metrics
        WHERE account_id = %s AND location_id = %s AND date = %s
        """,
        (account_id, location_id, business_date),
    )
    for row in rows:
        for field_name in (
            "sold",
            "prepared",
            "sold_out",
            "stockout_detected_by",
            "time_last_sale",
            "input_source",
        ):
            _append_correction(
                conn=conn,
                account_id=account_id,
                location_id=location_id,
                business_date=business_date,
                category=str(row["category"]),
                field_name=field_name,
                old_value=row[field_name],
                new_value=None,
                corrected_by=corrected_by,
                reason=reason,
            )


def _audit_daily_changes(
    conn: Any,
    account_id: str,
    location_id: str,
    business_date: date,
    existing: dict[str, Any] | None,
    updates: dict[str, Any],
    corrected_by: str,
    reason: str,
) -> None:
    """Append data-correction rows for changed daily metric fields."""

    for field_name, old_value, new_value in correction_changes(existing, updates):
        _append_correction(
            conn=conn,
            account_id=account_id,
            location_id=location_id,
            business_date=business_date,
            category=None,
            field_name=field_name,
            old_value=old_value,
            new_value=new_value,
            corrected_by=corrected_by,
            reason=reason,
        )


def _audit_category_changes(
    conn: Any,
    account_id: str,
    location_id: str,
    business_date: date,
    category: str,
    existing: dict[str, Any] | None,
    updates: dict[str, Any],
    corrected_by: str,
    reason: str,
) -> None:
    """Append data-correction rows for changed category metric fields."""

    for field_name, old_value, new_value in correction_changes(existing, updates):
        _append_correction(
            conn=conn,
            account_id=account_id,
            location_id=location_id,
            business_date=business_date,
            category=category,
            field_name=field_name,
            old_value=old_value,
            new_value=new_value,
            corrected_by=corrected_by,
            reason=reason,
        )


def _append_correction(
    conn: Any,
    account_id: str,
    location_id: str,
    business_date: date,
    category: str | None,
    field_name: str,
    old_value: Any,
    new_value: Any,
    corrected_by: str,
    reason: str,
) -> None:
    """Insert one canonical data correction audit record."""

    conn.execute(
        """
        INSERT INTO data_corrections (
            account_id, location_id, date, category, field_name,
            old_value, new_value, corrected_by, reason
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            account_id,
            location_id,
            business_date,
            category,
            field_name,
            _audit_value(old_value),
            _audit_value(new_value),
            corrected_by,
            reason,
        ),
    )


def _audit_value(value: Any) -> str | None:
    """Convert an audited value into stable text for storage."""

    if value is None:
        return None
    return str(value)


def _as_date(value: Any) -> date:
    """Convert a date-like value into a plain date."""

    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    return cast(date, pd.Timestamp(value).date())


def _minutes_from_time(value: Any) -> int | None:
    """Convert a time-like value into minutes after midnight."""

    if value is None or pd.isna(value):
        return None
    if isinstance(value, time):
        return value.hour * 60 + value.minute
    if isinstance(value, datetime):
        return value.hour * 60 + value.minute
    if isinstance(value, pd.Timestamp):
        return int(value.hour) * 60 + int(value.minute)
    if isinstance(value, str):
        parts = value.split(":")
        if len(parts) >= 2:
            return int(parts[0]) * 60 + int(parts[1])
    raise ValueError(f"Unsupported time value: {value!r}")


def _format_minutes(minutes: int) -> str:
    """Format minutes after midnight as HH:MM."""

    hour, minute = divmod(minutes, 60)
    return f"{hour:02d}:{minute:02d}"


def _daypart_weight(progress: float) -> float:
    """Return a demo cafe traffic weight for a point in the service day."""

    morning = 1.15 * math.exp(-((progress - 0.28) / 0.18) ** 2)
    lunch = 1.55 * math.exp(-((progress - 0.66) / 0.20) ** 2)
    late = 0.35 * math.exp(-((progress - 0.88) / 0.16) ** 2)
    return 0.35 + morning + lunch + late
