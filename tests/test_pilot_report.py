"""Tests for the pure pilot-readiness report assembly and phase partitioning."""

from __future__ import annotations

from datetime import date

from dialin.pilot_report import build_pilot_report_markdown, summarize_rows
from dialin.repository.pilot import phase_for_date


def _windows() -> list[dict[str, object]]:
    return [
        {"phase": "baseline", "start_date": date(2026, 1, 1), "end_date": date(2026, 1, 14)},
        {"phase": "live", "start_date": date(2026, 1, 15), "end_date": None},
    ]


def test_phase_for_date_assigns_baseline_live_and_none() -> None:
    """A date should map to the window that covers it, or None when uncovered."""

    windows = _windows()
    assert phase_for_date(date(2026, 1, 5), windows) == "baseline"
    assert phase_for_date(date(2026, 1, 20), windows) == "live"
    assert phase_for_date(date(2025, 12, 31), windows) is None


def test_phase_for_date_prefers_latest_start_on_overlap() -> None:
    """When windows overlap, the one with the later start wins."""

    windows = [
        {"phase": "baseline", "start_date": date(2026, 1, 1), "end_date": None},
        {"phase": "live", "start_date": date(2026, 1, 15), "end_date": None},
    ]
    assert phase_for_date(date(2026, 2, 1), windows) == "live"


def test_summarize_rows_counts_waste_sellouts_and_adherence() -> None:
    """Row aggregation should track proxies and the followed/overridden split."""

    rows = [
        {"recommended_prep": 40, "actual_prepared": 38, "sold": 35, "sold_out": False,
         "adhered": True},
        {"recommended_prep": 30, "actual_prepared": 30, "sold": 30, "sold_out": True,
         "adhered": False},
    ]
    summary = summarize_rows(rows)
    assert summary["days"] == 2
    assert summary["dialin_waste_proxy"] == 5  # (40-35) + max(30-30,0)
    assert summary["sellouts"] == 1
    assert summary["adhered"] == 1
    assert summary["overridden"] == 1


def test_summarize_rows_counts_unique_business_dates() -> None:
    rows = [
        {"date": date(2026, 1, 5), "recommended_prep": 40, "actual_prepared": 38,
         "sold": 35, "sold_out": False, "adhered": True},
        {"date": date(2026, 1, 5), "recommended_prep": 20, "actual_prepared": 20,
         "sold": 18, "sold_out": False, "adhered": True},
    ]

    assert summarize_rows(rows)["days"] == 1


def test_pilot_report_is_honest_and_partitioned() -> None:
    """The report must partition by phase and never claim validated ROI."""

    rows = [
        {"date": date(2026, 1, 5), "category": "sweet", "recommended_prep": 40,
         "actual_prepared": 38, "sold": 35, "sold_out": False, "adhered": True},
        {"date": date(2026, 1, 20), "category": "sweet", "recommended_prep": 42,
         "actual_prepared": 42, "sold": 42, "sold_out": True, "adhered": False},
    ]
    gates = [
        {"category": "sweet", "status": "shadow", "evaluated_days": 12,
         "beats_baselines": False, "range_coverage": 0.7, "signed_error": -1.0},
    ]
    report = build_pilot_report_markdown(
        account_label="acct_fadri",
        location_label="loc_fadri_main",
        generated_on=date(2026, 1, 21),
        windows=_windows(),
        profile={"responses": {"open_days_per_week": 6}, "values_source": "owner_confirmed"},
        gates=gates,
        scorecard_rows=rows,
        synthetic=True,
    )

    lowered = report.lower()
    assert "not validated roi" in lowered  # honest disclaimer present
    assert "generated revenue" not in lowered  # no overclaim
    assert "proven savings" not in lowered
    assert "Demo data" in report
    assert "| baseline |" in report
    assert "| live |" in report
    assert "Model gates" in report
    assert "Open days per week: 6" in report
