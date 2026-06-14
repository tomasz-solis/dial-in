"""Per-category unit economics and the derived service quantile."""

from __future__ import annotations

from datetime import date
from typing import Any

from dialin.db import account_connection, fetch_all, fetch_one
from dialin.engine import service_quantile


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

