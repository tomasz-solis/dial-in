"""Tests for POS CSV import parsing."""

from __future__ import annotations

from datetime import date

import pytest

from dialin.pos_import import (
    CategoryMapping,
    PosColumnMapping,
    csv_columns,
    parse_keyword_text,
    preview_pos_import,
)


def test_valid_line_item_csv_rolls_up_timestamped_quantities() -> None:
    """Valid line items should aggregate by business date and category."""

    preview = preview_pos_import(
        csv_text=(
            "Date,Time,Item,Qty\n"
            "2026-05-31,2026-05-31 09:15,Latte,2\n"
            "2026-05-31,2026-05-31 11:30,Croissant,3\n"
            "2026-05-31,2026-05-31 12:05,Toast,1\n"
        ),
        columns=PosColumnMapping("Date", "Item", "Time", "Qty"),
        categories=_category_mapping(),
        timezone_name="Europe/Madrid",
    )

    assert preview.rows_read == 3
    assert preview.rows_imported == 3
    assert preview.rows_rejected == 0
    assert preview.date_start == date(2026, 5, 31)
    assert preview.timestamp_coverage == 1.0
    assert preview.mapped_totals == {"drinks": 2, "sweet": 3, "savory": 1}
    assert preview.can_apply


def test_csv_without_timestamp_column_is_valid_with_zero_coverage() -> None:
    """Timestamp columns are optional and should only control coverage."""

    preview = preview_pos_import(
        csv_text="Date,Item,Qty\n2026-05-31,Americano,2\n",
        columns=PosColumnMapping("Date", "Item", quantity_column="Qty"),
        categories=_category_mapping(),
        timezone_name="Europe/Madrid",
    )

    assert preview.rows_imported == 1
    assert preview.timestamp_coverage == 0.0
    assert preview.rollups[0].first_sale_at is None


def test_csv_without_quantity_column_defaults_to_one_unit() -> None:
    """Missing quantity mapping should default each accepted line item to one unit."""

    preview = preview_pos_import(
        csv_text="Date,Item\n2026-05-31,Croissant\n2026-05-31,Croissant\n",
        columns=PosColumnMapping("Date", "Item"),
        categories=_category_mapping(),
        timezone_name="Europe/Madrid",
    )

    assert preview.mapped_totals["sweet"] == 2


def test_invalid_rows_are_rejected_with_clear_reasons() -> None:
    """Bad input rows should be preview errors, not parser crashes."""

    preview = preview_pos_import(
        csv_text=(
            "Date,Time,Item,Qty\n"
            ",09:00,Latte,1\n"
            "2026-05-31,09:05,,1\n"
            "2026-05-31,09:10,Latte Croissant,1\n"
            "2026-05-31,09:15,Unknown item,1\n"
            "2026-05-31,not-a-time,Latte,1\n"
            "2026-05-31,09:25,Latte,0\n"
        ),
        columns=PosColumnMapping("Date", "Item", "Time", "Qty"),
        categories=_category_mapping(),
        timezone_name="Europe/Madrid",
    )

    assert preview.rows_imported == 0
    assert [error.reason for error in preview.errors] == [
        "missing or invalid date",
        "blank item name",
        "ambiguous category match",
        "no category match",
        "invalid timestamp",
        "non-positive or invalid quantity",
    ]
    assert not preview.can_apply


def test_import_without_drinks_is_previewable_but_not_applyable() -> None:
    """A mapped import without drinks should not be allowed to update history."""

    preview = preview_pos_import(
        csv_text="Date,Item,Qty\n2026-05-31,Croissant,4\n",
        columns=PosColumnMapping("Date", "Item", quantity_column="Qty"),
        categories=_category_mapping(),
        timezone_name="Europe/Madrid",
    )

    assert preview.rows_imported == 1
    assert preview.mapped_totals["drinks"] == 0
    assert not preview.can_apply


def test_keyword_and_header_helpers_are_stable() -> None:
    """UI helpers should parse common operator input without preserving duplicates."""

    assert parse_keyword_text("Latte, coffee\nlatte") == ("latte", "coffee")
    assert csv_columns("Date,Item\n2026-05-31,Latte\n") == ["Date", "Item"]


def test_missing_mapped_columns_raise_before_row_parsing() -> None:
    """Column mappings should fail clearly when the CSV lacks a selected column."""

    with pytest.raises(ValueError, match="missing mapped columns"):
        preview_pos_import(
            csv_text="Date,Item\n2026-05-31,Latte\n",
            columns=PosColumnMapping("Date", "Missing"),
            categories=_category_mapping(),
            timezone_name="Europe/Madrid",
        )


def _category_mapping() -> CategoryMapping:
    """Return a compact category mapping for parser tests."""

    return CategoryMapping(
        drinks_keywords=("latte", "americano"),
        sweet_keywords=("croissant",),
        savory_keywords=("toast",),
    )
