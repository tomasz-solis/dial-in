"""Tests for repository attribution helpers."""

from __future__ import annotations

from datetime import date, time

import pytest

from dialin.repository import (
    build_intraday_pressure_curve,
    correction_changes,
    correction_input_source,
    economics_service_quantile,
    effective_location_hours,
    expected_intraday_drinks,
    insert_manual_event,
    normalize_menu_version,
    normalize_override_reason,
    recommendation_adhered,
    upsert_location_hours,
)


def test_recommendation_adherence_uses_minimum_and_percent_tolerance() -> None:
    """Prepared quantities should count as followed inside the PRD tolerance."""

    assert recommendation_adhered(prepared=51, recommended_prep=50)
    assert recommendation_adhered(prepared=55, recommended_prep=50)
    assert not recommendation_adhered(prepared=56, recommended_prep=50)
    assert recommendation_adhered(prepared=10, recommended_prep=12)


def test_override_reason_normalization_keeps_only_real_reasons() -> None:
    """Blank and default override reasons should not be stored."""

    assert normalize_override_reason(None) is None
    assert normalize_override_reason("") is None
    assert normalize_override_reason("No reason") is None
    assert normalize_override_reason(" supplier issue ") == "supplier issue"


def test_menu_version_normalization_defaults_blank_values() -> None:
    """Blank menu versions should fall back to the stable initial version."""

    assert normalize_menu_version(None) == "v1"
    assert normalize_menu_version("") == "v1"
    assert normalize_menu_version("  summer-2026  ") == "summer-2026"


def test_correction_changes_only_reports_real_changes() -> None:
    """Correction comparison should ignore unchanged fields."""

    existing = {"sold": 12, "prepared": 15, "input_source": "confirmed"}
    updates = {"sold": 12, "prepared": 16}

    assert correction_changes(existing, updates) == [("prepared", 15, 16)]
    assert correction_changes(None, updates) == []


def test_correction_input_source_marks_edited_rows() -> None:
    """Existing rows should become corrected only when operational values change."""

    existing = {"sold": 12, "prepared": 15, "input_source": "confirmed"}

    assert correction_input_source(None, {"sold": 12}) == "confirmed"
    assert correction_input_source(existing, {"sold": 12, "prepared": 15}) == "confirmed"
    assert correction_input_source(existing, {"sold": 12, "prepared": 16}) == "corrected"
    assert correction_input_source(
        {"sold": 12, "input_source": "imputed"},
        {"sold": 12},
    ) == "imputed"


def test_effective_location_hours_uses_latest_active_row() -> None:
    """Opening hours should be selected by weekday and effective date."""

    rows = [
        {
            "day_of_week": 4,
            "is_open": True,
            "open_time": time(8, 0),
            "close_time": time(15, 0),
            "effective_from": date(2026, 1, 1),
            "effective_to": None,
            "source": "demo_seed",
        },
        {
            "day_of_week": 4,
            "is_open": True,
            "open_time": time(9, 0),
            "close_time": time(16, 0),
            "effective_from": date(2026, 5, 1),
            "effective_to": None,
            "source": "owner_confirmed",
        },
    ]

    hours = effective_location_hours(rows, date(2026, 5, 29), open_days=[])

    assert hours["open_time"] == time(9, 0)
    assert hours["close_time"] == time(16, 0)
    assert hours["source"] == "owner_confirmed"


def test_effective_location_hours_falls_back_to_open_days() -> None:
    """Locations without hours rows should still get a conservative service window."""

    hours = effective_location_hours([], date(2026, 6, 2), open_days=[1, 2, 3])

    assert hours["is_open"] is True
    assert hours["open_time"] == time(8, 0)
    assert hours["close_time"] == time(16, 0)


def test_expected_intraday_drinks_prefers_observed_closeout() -> None:
    """Intraday pressure should use actual daily traffic when it is available."""

    expected, source = expected_intraday_drinks(
        {"is_open": True, "drinks_sold": 143, "input_source": "confirmed"},
        [{"date": date(2026, 5, 22), "drinks_sold": 120}],
        date(2026, 5, 29),
    )

    assert expected == 143
    assert source == "observed closeout"


def test_intraday_pressure_curve_scales_to_expected_drinks() -> None:
    """The demo daypart curve should distribute the expected daily traffic."""

    curve = build_intraday_pressure_curve(time(8, 0), time(16, 0), expected_drinks=160)

    assert len(curve) == 16
    assert sum(row["expected_drinks"] for row in curve) == pytest.approx(160, abs=0.5)
    assert max(row["pressure_index"] for row in curve) > min(
        row["pressure_index"] for row in curve
    )


def test_economics_service_quantile_uses_newsvendor_costs() -> None:
    """Economic inputs should produce the same operating quantile as the PRD example."""

    quantile = economics_service_quantile(
        retail_price=3.5,
        unit_cogs=0.9,
        salvage_share_default=0.0,
        attached_drink_margin=1.5,
        attach_and_balk_rate=0.4,
    )

    assert quantile == pytest.approx(0.7805, abs=0.0001)


def test_economics_service_quantile_rejects_unusable_costs() -> None:
    """Invalid economics should fail before they reach Postgres."""

    with pytest.raises(ValueError, match="Unit COGS"):
        economics_service_quantile(
            retail_price=3.5,
            unit_cogs=0.0,
            salvage_share_default=0.0,
            attached_drink_margin=1.5,
            attach_and_balk_rate=0.4,
        )


def test_upsert_location_hours_rejects_invalid_open_window() -> None:
    """Opening-hours writes should fail before hitting Postgres when times are unusable."""

    with pytest.raises(ValueError, match="Closing time"):
        upsert_location_hours(
            database_url="postgresql://example",
            account_id="acct",
            location_id="loc",
            day_of_week=1,
            is_open=True,
            open_time=time(13, 0),
            close_time=time(9, 0),
            effective_from=date(2026, 6, 1),
        )


def test_insert_manual_event_rejects_blank_event_name() -> None:
    """Manual event logging should not create empty context rows."""

    with pytest.raises(ValueError, match="Event name"):
        insert_manual_event(
            database_url="postgresql://example",
            account_id="acct",
            location_id="loc",
            business_date=date(2026, 6, 1),
            event_name=" ",
            event_type="market",
            impact_score=0.1,
            confidence="Medium",
        )
