"""Closeout entry, missing/closed days, and the correction audit trail."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, tzinfo
from typing import Any
from zoneinfo import ZoneInfo

from dialin.db import account_connection, fetch_all, fetch_one

OVERRIDE_REASON_OPTIONS = (
    "weather felt wrong",
    "supplier issue",
    "large order",
    "owner judgement",
    "other",
)


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
          AND is_active = true
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
          AND is_active = true
        """,
        (account_id, location_id, business_date),
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
