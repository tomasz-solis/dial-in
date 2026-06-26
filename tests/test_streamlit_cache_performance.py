"""Static and unit checks for Streamlit payload performance contracts."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from dialin import streamlit_cache

SOURCE = Path("src/dialin/streamlit_cache.py").read_text(encoding="utf-8")


def test_today_payload_does_not_fetch_recommendation_audit_snapshots() -> None:
    """The daily Today view should read only display columns from recommendations."""

    source = _function_source("fetch_today_payload", "fetch_closeout_payload")

    assert "SELECT *" not in source
    assert "input_snapshot" not in source
    assert "config_snapshot" not in source
    assert "top_drivers" in source


def test_closeout_payload_uses_bounded_prefill_frames() -> None:
    """Closeout should not load all observed history just to render one form."""

    payload_source = _function_source("fetch_closeout_payload", "fetch_setup_payload")
    helper_source = _function_source("_closeout_frames", "_location_hours_plan")

    assert "_closeout_frames" in payload_source
    assert "CLOSEOUT_DEFAULT_HISTORY_DAYS" in helper_source
    assert "SELECT *" not in helper_source
    assert "date >= %s" in helper_source
    assert "pos_daily_sales" in helper_source


def test_performance_payload_is_bounded_and_reuses_matched_rows() -> None:
    """Performance should use one bounded payload instead of repeated broad reads."""

    source = _function_source("fetch_performance_payload", "_CACHED_READS")

    assert "PERFORMANCE_HISTORY_DAYS" in source
    assert "r.date >= %s" in source
    assert "_scorecard_from_rows(outcomes)" in source
    assert "r.probe_active" in source
    assert "r.probe_extra_units" in source
    assert "pilot_windows" in source
    assert "pilot_profile" in source
    assert "SELECT *" not in source
    assert "LIMIT %s" in source


def test_bootstrap_checks_runtime_schema_before_view_queries() -> None:
    source = _function_source("app_bootstrap", "list_locations")

    assert "_runtime_schema_gaps(conn)" in source
    assert "Database schema is behind this app release" in source
    assert ("weather", "forecast_source") in streamlit_cache.RUNTIME_SCHEMA_REQUIREMENTS
    assert (
        "recommendations",
        "probe_extra_units",
    ) in streamlit_cache.RUNTIME_SCHEMA_REQUIREMENTS


def test_scorecard_from_rows_matches_repository_summary_shape() -> None:
    """The consolidated Performance payload should preserve scorecard semantics."""

    scorecard = streamlit_cache._scorecard_from_rows(
        [
            {
                "date": date(2026, 5, 31),
                "category": "sweet",
                "recommended_prep": 24,
                "recommendation_prepared": 26,
                "adhered": True,
                "override_delta": 0,
                "override_reason": None,
                "sold": 20,
                "actual_prepared": 26,
                "sold_out": False,
            },
            {
                "date": date(2026, 5, 31),
                "category": "savory",
                "recommended_prep": 12,
                "recommendation_prepared": 18,
                "adhered": False,
                "override_delta": 6,
                "override_reason": "large order",
                "sold": 16,
                "actual_prepared": 18,
                "sold_out": True,
            },
        ]
    )

    assert scorecard["actual_waste"] == 8
    assert scorecard["dialin_waste_proxy"] == 4
    assert scorecard["actual_sellouts"] == 1
    assert scorecard["dialin_short_proxy"] == 1
    assert scorecard["attributed_rows"] == 2
    assert scorecard["adhered_rows"] == 1
    assert scorecard["overridden_rows"] == 1


def _function_source(name: str, next_name: str) -> str:
    """Return the source slice for a function in streamlit_cache.py."""

    start = SOURCE.index(f"def {name}")
    marker = f"\ndef {next_name}"
    if marker not in SOURCE[start:]:
        marker = f"\n{next_name}"
    end = SOURCE.index(marker, start)
    return SOURCE[start:end]
