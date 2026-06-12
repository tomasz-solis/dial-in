"""Tests for honest model-quality metrics."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from dialin.metrics import (
    calibration_coverage,
    evaluate_model_vs_baselines,
    naive_baseline_forecasts,
    pinball_loss,
)


def test_pinball_loss_matches_hand_computed_values() -> None:
    """Quantile loss should penalise under-forecast by q and over-forecast by 1-q."""

    assert pinball_loss(actual=50, forecast=40, quantile=0.78) == pytest.approx(7.8)
    assert pinball_loss(actual=40, forecast=50, quantile=0.78) == pytest.approx(2.2)
    assert pinball_loss(actual=40, forecast=40, quantile=0.78) == pytest.approx(0.0)


def test_pinball_loss_rejects_invalid_quantiles() -> None:
    """Quantiles at or beyond the unit interval are configuration errors."""

    with pytest.raises(ValueError):
        pinball_loss(actual=10, forecast=10, quantile=1.0)


def test_naive_baselines_use_same_weekday_history() -> None:
    """Baselines should read seven-day lags, never adjacent days."""

    dates = pd.date_range("2026-01-03", periods=5, freq="7D").date
    frame = pd.DataFrame(
        {
            "date": dates,
            "category": ["sweet"] * 5,
            "sold": [30, 34, 38, 42, 46],
        }
    )

    baselines = naive_baseline_forecasts(frame)

    last_row = baselines.iloc[-1]
    assert last_row["last_week_sold"] == 42
    assert last_row["trailing_4wk_sold"] == pytest.approx((30 + 34 + 38 + 42) / 4)
    assert pd.isna(baselines.iloc[0]["last_week_sold"])


def test_model_beats_baselines_verdict() -> None:
    """A forecast closer to actual sales should win on pinball loss."""

    dates = pd.date_range("2026-01-03", periods=6, freq="7D").date
    history = pd.DataFrame(
        {
            "date": dates,
            "category": ["sweet"] * 6,
            "sold": [30, 32, 34, 36, 38, 40],
        }
    )
    matched = pd.DataFrame(
        {
            "date": [dates[4], dates[5]],
            "category": ["sweet", "sweet"],
            "recommended_prep": [38, 40],
            "service_quantile": [0.78, 0.78],
            "sold": [38, 40],
            "sold_out": [False, False],
        }
    )

    evaluation = evaluate_model_vs_baselines(matched, history)

    assert evaluation["evaluated_rows"] == 2
    assert evaluation["model_pinball"] == pytest.approx(0.0)
    assert evaluation["beats_last_week"] is True
    assert evaluation["beats_trailing"] is True
    assert evaluation["beats_baselines"] is True


def test_evaluation_excludes_censored_rows_and_reports_share() -> None:
    """Sold-out rows must not be scored, and their share must be visible."""

    dates = pd.date_range("2026-01-03", periods=6, freq="7D").date
    history = pd.DataFrame(
        {
            "date": dates,
            "category": ["sweet"] * 6,
            "sold": [30, 32, 34, 36, 38, 40],
        }
    )
    matched = pd.DataFrame(
        {
            "date": [dates[4], dates[5]],
            "category": ["sweet", "sweet"],
            "recommended_prep": [38, 10],
            "service_quantile": [0.78, 0.78],
            "sold": [38, 40],
            "sold_out": [False, True],
        }
    )

    evaluation = evaluate_model_vs_baselines(matched, history)

    assert evaluation["evaluated_rows"] == 1
    assert evaluation["censored_rows"] == 1
    assert evaluation["censored_share"] == pytest.approx(0.5)
    assert evaluation["model_pinball"] == pytest.approx(0.0)


def test_calibration_coverage_counts_uncensored_rows_only() -> None:
    """Coverage uses uncensored days; censored days are excluded but counted."""

    matched = pd.DataFrame(
        {
            "date": [date(2026, 1, day) for day in (1, 2, 3, 4)],
            "category": ["sweet"] * 4,
            "sold": [30, 50, 33, 40],
            "sold_out": [False, False, False, True],
            "demand_p_lower": [28, 28, 28, 28],
            "demand_p_upper": [36, 36, 36, 36],
            "confidence": ["High", "High", "Low", "High"],
        }
    )

    calibration = calibration_coverage(matched)

    assert calibration["uncensored_rows"] == 3
    assert calibration["censored_rows"] == 1
    assert calibration["censored_share"] == pytest.approx(0.25)
    assert calibration["coverage"] == pytest.approx(2 / 3, abs=1e-4)
    assert calibration["by_confidence"]["High"]["rows"] == 2
    assert calibration["by_confidence"]["High"]["coverage"] == pytest.approx(0.5)
    assert calibration["by_confidence"]["Low"]["coverage"] == pytest.approx(1.0)


def test_calibration_coverage_handles_empty_and_fully_censored_input() -> None:
    """Degenerate inputs should report honestly instead of crashing."""

    empty = calibration_coverage(pd.DataFrame())
    assert empty["coverage"] is None

    censored = calibration_coverage(
        pd.DataFrame(
            {
                "date": [date(2026, 1, 1)],
                "category": ["sweet"],
                "sold": [40],
                "sold_out": [True],
                "demand_p_lower": [28],
                "demand_p_upper": [36],
                "confidence": ["High"],
            }
        )
    )
    assert censored["coverage"] is None
    assert censored["censored_share"] == pytest.approx(1.0)
