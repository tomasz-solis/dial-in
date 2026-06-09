"""Pure CSV parsing helpers for POS backfill imports."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any, cast
from zoneinfo import ZoneInfo

import pandas as pd

POS_CATEGORIES = ("drinks", "sweet", "savory")


@dataclass(frozen=True)
class PosColumnMapping:
    """CSV columns used by the line-item POS importer."""

    date_column: str
    item_column: str
    timestamp_column: str | None = None
    quantity_column: str | None = None


@dataclass(frozen=True)
class CategoryMapping:
    """Case-insensitive item-name keywords for the three imported sales categories."""

    drinks_keywords: tuple[str, ...]
    sweet_keywords: tuple[str, ...]
    savory_keywords: tuple[str, ...]


@dataclass(frozen=True)
class PosImportError:
    """One rejected POS CSV row."""

    row_number: int
    reason: str
    raw_row: dict[str, str]


@dataclass(frozen=True)
class DailySalesRollup:
    """Daily imported sales for one category."""

    business_date: date
    category: str
    units_sold: int
    first_sale_at: datetime | None
    last_sale_at: datetime | None


@dataclass(frozen=True)
class PosImportPreview:
    """Preview summary for a parsed POS CSV import."""

    rows_read: int
    rows_imported: int
    rows_rejected: int
    date_start: date | None
    date_end: date | None
    timestamp_coverage: float
    rollups: tuple[DailySalesRollup, ...]
    errors: tuple[PosImportError, ...]
    mapped_totals: dict[str, int]

    @property
    def can_apply(self) -> bool:
        """Return whether this preview has enough mapped sales to apply."""

        return self.rows_imported > 0 and self.mapped_totals.get("drinks", 0) > 0


def parse_keyword_text(value: str) -> tuple[str, ...]:
    """Parse comma- or newline-separated keyword text into normalized keywords."""

    raw_parts = value.replace("\n", ",").split(",")
    keywords = tuple(part.strip().casefold() for part in raw_parts if part.strip())
    return tuple(dict.fromkeys(keywords))


def csv_columns(csv_text: str) -> list[str]:
    """Return CSV header columns in file order."""

    reader = csv.DictReader(io.StringIO(csv_text))
    return [] if reader.fieldnames is None else [str(column) for column in reader.fieldnames]


def mapping_snapshot(
    columns: PosColumnMapping,
    categories: CategoryMapping,
) -> dict[str, Any]:
    """Return a JSON-ready snapshot of the import mapping."""

    return {
        "columns": {
            "date_column": columns.date_column,
            "item_column": columns.item_column,
            "timestamp_column": columns.timestamp_column,
            "quantity_column": columns.quantity_column,
        },
        "categories": {
            "drinks_keywords": list(categories.drinks_keywords),
            "sweet_keywords": list(categories.sweet_keywords),
            "savory_keywords": list(categories.savory_keywords),
        },
    }


def preview_pos_import(
    csv_text: str,
    columns: PosColumnMapping,
    categories: CategoryMapping,
    timezone_name: str,
) -> PosImportPreview:
    """Parse a line-item POS CSV into a preview without writing to storage."""

    _validate_columns(csv_text, columns)
    timezone = ZoneInfo(timezone_name)
    rows_read = 0
    timestamped_rows = 0
    errors: list[PosImportError] = []
    accepted: list[tuple[date, str, int, datetime | None]] = []

    reader = csv.DictReader(io.StringIO(csv_text))
    for row_number, row in enumerate(reader, start=2):
        clean_row = {str(key): "" if value is None else str(value) for key, value in row.items()}
        rows_read += 1
        parsed = _parse_row(clean_row, row_number, columns, categories, timezone)
        if isinstance(parsed, PosImportError):
            errors.append(parsed)
            continue
        business_date, category, quantity, sold_at = parsed
        if sold_at is not None:
            timestamped_rows += 1
        accepted.append((business_date, category, quantity, sold_at))

    rollups = _roll_up_sales(accepted)
    mapped_totals = dict.fromkeys(POS_CATEGORIES, 0)
    for rollup in rollups:
        mapped_totals[rollup.category] += rollup.units_sold
    dates = [rollup.business_date for rollup in rollups]
    timestamp_coverage = 0.0 if not accepted else timestamped_rows / len(accepted)
    return PosImportPreview(
        rows_read=rows_read,
        rows_imported=len(accepted),
        rows_rejected=len(errors),
        date_start=min(dates) if dates else None,
        date_end=max(dates) if dates else None,
        timestamp_coverage=round(timestamp_coverage, 4),
        rollups=tuple(rollups),
        errors=tuple(errors),
        mapped_totals=mapped_totals,
    )


def _validate_columns(csv_text: str, columns: PosColumnMapping) -> None:
    """Raise when the mapping references missing CSV columns."""

    available = set(csv_columns(csv_text))
    required = [columns.date_column, columns.item_column]
    if columns.timestamp_column is not None:
        required.append(columns.timestamp_column)
    if columns.quantity_column is not None:
        required.append(columns.quantity_column)
    missing = [column for column in required if column not in available]
    if missing:
        raise ValueError(f"CSV is missing mapped columns: {missing}")


def _parse_row(
    row: dict[str, str],
    row_number: int,
    columns: PosColumnMapping,
    categories: CategoryMapping,
    timezone: ZoneInfo,
) -> tuple[date, str, int, datetime | None] | PosImportError:
    """Parse one CSV row into a normalized sales tuple."""

    business_date = _parse_date(row.get(columns.date_column, ""))
    if business_date is None:
        return PosImportError(row_number, "missing or invalid date", row)

    item_name = row.get(columns.item_column, "").strip()
    if not item_name:
        return PosImportError(row_number, "blank item name", row)

    category = _match_category(item_name, categories)
    if category is None:
        return PosImportError(row_number, "no category match", row)
    if category == "ambiguous":
        return PosImportError(row_number, "ambiguous category match", row)

    quantity = _parse_quantity(
        None if columns.quantity_column is None else row.get(columns.quantity_column, "")
    )
    if quantity is None:
        return PosImportError(row_number, "non-positive or invalid quantity", row)

    sold_at = None
    if columns.timestamp_column is not None:
        raw_timestamp = row.get(columns.timestamp_column, "").strip()
        if raw_timestamp:
            sold_at = _parse_timestamp(raw_timestamp, business_date, timezone)
            if sold_at is None:
                return PosImportError(row_number, "invalid timestamp", row)

    return business_date, category, quantity, sold_at


def _parse_date(value: str) -> date | None:
    """Parse a CSV business date."""

    if not value.strip():
        return None
    try:
        return cast(date, pd.Timestamp(value).date())
    except Exception:
        return None


def _parse_timestamp(value: str, business_date: date, timezone: ZoneInfo) -> datetime | None:
    """Parse a timestamp or time-only value into a timezone-aware datetime."""

    try:
        if ":" in value and not any(separator in value for separator in ("-", "/")):
            clock = time.fromisoformat(value)
            return datetime.combine(business_date, clock, tzinfo=timezone)
        timestamp = pd.Timestamp(value)
        if pd.isna(timestamp):
            return None
        if timestamp.tzinfo is None:
            timestamp = timestamp.tz_localize(timezone.key)
        else:
            timestamp = timestamp.tz_convert(timezone.key)
        return cast(datetime, timestamp.to_pydatetime())
    except Exception:
        return None


def _parse_quantity(value: str | None) -> int | None:
    """Parse a positive whole-unit quantity, defaulting missing columns to one."""

    if value is None:
        return 1
    stripped = value.strip()
    if not stripped:
        return None
    try:
        quantity = float(stripped)
    except ValueError:
        return None
    if quantity <= 0 or not quantity.is_integer():
        return None
    return int(quantity)


def _match_category(item_name: str, categories: CategoryMapping) -> str | None:
    """Return the category matched by an item name, or an ambiguity marker."""

    normalized = item_name.casefold()
    matches: list[str] = []
    keyword_sets = {
        "drinks": categories.drinks_keywords,
        "sweet": categories.sweet_keywords,
        "savory": categories.savory_keywords,
    }
    for category, keywords in keyword_sets.items():
        if any(keyword and keyword in normalized for keyword in keywords):
            matches.append(category)
    if len(matches) > 1:
        return "ambiguous"
    return matches[0] if matches else None


def _roll_up_sales(rows: list[tuple[date, str, int, datetime | None]]) -> list[DailySalesRollup]:
    """Aggregate parsed line items into daily category rollups."""

    grouped: dict[tuple[date, str], dict[str, Any]] = {}
    for business_date, category, quantity, sold_at in rows:
        key = (business_date, category)
        group = grouped.setdefault(
            key,
            {"units_sold": 0, "timestamps": []},
        )
        group["units_sold"] += quantity
        if sold_at is not None:
            group["timestamps"].append(sold_at)

    rollups: list[DailySalesRollup] = []
    for (business_date, category), values in sorted(grouped.items()):
        timestamps = sorted(values["timestamps"])
        rollups.append(
            DailySalesRollup(
                business_date=business_date,
                category=category,
                units_sold=int(values["units_sold"]),
                first_sale_at=timestamps[0] if timestamps else None,
                last_sale_at=timestamps[-1] if timestamps else None,
            )
        )
    return rollups
