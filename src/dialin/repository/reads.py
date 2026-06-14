"""History frames, business-date lookups, and proxy scorecard reads."""

from __future__ import annotations

from datetime import date
from typing import Any, cast

import pandas as pd

from dialin.db import account_connection, fetch_all, fetch_one


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

