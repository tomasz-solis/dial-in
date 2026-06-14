"""POS CSV import application and recent-run reads."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from typing import Any

from dialin.db import account_connection, fetch_all, fetch_one
from dialin.pos_import import PosImportPreview


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
        drink_dates = {
            rollup.business_date for rollup in preview.rollups if rollup.category == "drinks"
        }
        _clear_removed_imported_drinks(
            conn=conn,
            account_id=account_id,
            location_id=location_id,
            date_start=preview.date_start,
            date_end=preview.date_end,
            replacement_dates=drink_dates,
            recorded_at=applied_at,
            corrected_by=created_by,
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
                    corrected_by=created_by,
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


def _upsert_imported_drinks(
    conn: Any,
    account_id: str,
    location_id: str,
    business_date: date,
    timezone_name: str,
    drinks_sold: int,
    recorded_at: datetime,
    corrected_by: str,
) -> None:
    """Upsert imported POS drinks into the daily traffic history."""

    existing = _fetch_daily_metric(conn, account_id, location_id, business_date)
    if existing is not None and str(existing.get("input_source")) in {"confirmed", "corrected"}:
        if existing.get("drinks_sold") != drinks_sold:
            _append_pos_correction(
                conn=conn,
                account_id=account_id,
                location_id=location_id,
                business_date=business_date,
                field_name="drinks_sold",
                old_value=existing.get("drinks_sold"),
                new_value=drinks_sold,
                corrected_by=corrected_by,
                reason="pos import skipped confirmed closeout",
            )
        return

    if existing is not None:
        updates = {
            "timezone": timezone_name,
            "is_open": True,
            "drinks_sold": drinks_sold,
            "input_source": "imported",
        }
        for field_name, new_value in updates.items():
            old_value = existing.get(field_name)
            if old_value != new_value:
                _append_pos_correction(
                    conn=conn,
                    account_id=account_id,
                    location_id=location_id,
                    business_date=business_date,
                    field_name=field_name,
                    old_value=old_value,
                    new_value=new_value,
                    corrected_by=corrected_by,
                    reason="pos import traffic update",
                )

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


def _clear_removed_imported_drinks(
    conn: Any,
    account_id: str,
    location_id: str,
    date_start: date,
    date_end: date,
    replacement_dates: set[date],
    recorded_at: datetime,
    corrected_by: str,
) -> None:
    """Clear imported traffic dates omitted by a replacement import window."""

    for business_date in _inclusive_dates(date_start, date_end):
        if business_date in replacement_dates:
            continue
        existing = _fetch_daily_metric(conn, account_id, location_id, business_date)
        if existing is None or existing.get("input_source") != "imported":
            continue
        _append_pos_correction(
            conn=conn,
            account_id=account_id,
            location_id=location_id,
            business_date=business_date,
            field_name="drinks_sold",
            old_value=existing.get("drinks_sold"),
            new_value=None,
            corrected_by=corrected_by,
            reason="pos import removed imported drinks row",
        )
        _append_pos_correction(
            conn=conn,
            account_id=account_id,
            location_id=location_id,
            business_date=business_date,
            field_name="input_source",
            old_value="imported",
            new_value="imputed",
            corrected_by=corrected_by,
            reason="pos import removed imported drinks row",
        )
        conn.execute(
            """
            UPDATE daily_metrics
            SET drinks_sold = NULL,
                input_source = 'imputed',
                recorded_at = %s
            WHERE account_id = %s
              AND location_id = %s
              AND date = %s
              AND input_source = 'imported'
            """,
            (recorded_at, account_id, location_id, business_date),
        )


def _fetch_daily_metric(
    conn: Any,
    account_id: str,
    location_id: str,
    business_date: date,
) -> dict[str, Any] | None:
    """Fetch one daily row before a POS import updates traffic."""

    return fetch_one(
        conn,
        """
        SELECT timezone, is_open, drinks_sold, input_source, menu_version
        FROM daily_metrics
        WHERE account_id = %s AND location_id = %s AND date = %s
        """,
        (account_id, location_id, business_date),
    )


def _append_pos_correction(
    conn: Any,
    account_id: str,
    location_id: str,
    business_date: date,
    field_name: str,
    old_value: Any,
    new_value: Any,
    corrected_by: str,
    reason: str,
) -> None:
    """Append a data-correction record for POS-driven traffic changes."""

    conn.execute(
        """
        INSERT INTO data_corrections (
            account_id, location_id, date, category, field_name,
            old_value, new_value, corrected_by, reason
        )
        VALUES (%s, %s, %s, NULL, %s, %s, %s, %s, %s)
        """,
        (
            account_id,
            location_id,
            business_date,
            field_name,
            None if old_value is None else str(old_value),
            None if new_value is None else str(new_value),
            corrected_by,
            reason,
        ),
    )


def _inclusive_dates(start: date, end: date) -> tuple[date, ...]:
    """Return calendar dates from start through end."""

    if start > end:
        return ()
    return tuple(start + timedelta(days=offset) for offset in range((end - start).days + 1))
