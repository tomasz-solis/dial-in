"""Tests for honest model-quality metrics."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from dialin.metrics import (
    calibration_coverage,
    calibration_coverage_truth,
    evaluate_against_truth,
    evaluate_model_vs_baselines,
    expected_misprep_cost,
    naive_baseline_forecasts,
    pinball_loss,
)


def _weekly_sweet_history() -> pd.DataFrame:
    """Six same-weekday sweet rows so 7-day-lag baselines resolve on the last two."""

    dates = pd.date_range("2026-01-03", periods=6, freq="7D").date
    return pd.DataFrame(
        {"date": dates, "category": ["sweet"] * 6, "sold": [40, 42, 44, 46, 48, 50]}
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


def test_evaluate_against_truth_scores_all_days() -> None:
    """The ground-truth lens scores sold-out days too, against true demand."""

    history = _weekly_sweet_history()
    dates = pd.date_range("2026-01-03", periods=6, freq="7D").date
    matched = pd.DataFrame(
        {
            "date": [dates[4], dates[5]],
            "category": ["sweet", "sweet"],
            "recommended_prep": [55, 58],
            "service_quantile": [0.78, 0.78],
            "true_demand": [55, 58],
            "sold_out": [False, True],
        }
    )

    evaluation = evaluate_against_truth(matched, history)

    # both days scored (the sold-out day is not excluded), and the model is exact
    assert evaluation["evaluated_rows"] == 2
    assert evaluation["model_pinball"] == pytest.approx(0.0)
    assert evaluation["beats_baselines"] is True


def test_calibration_coverage_truth_includes_sold_out_days() -> None:
    """Ground-truth coverage spans every day, censored or not."""

    matched = pd.DataFrame(
        {
            "date": [date(2026, 1, day) for day in (1, 2, 3)],
            "category": ["sweet"] * 3,
            "true_demand": [30, 33, 70],
            "sold_out": [False, False, True],
            "demand_p_lower": [28, 28, 28],
            "demand_p_upper": [36, 36, 36],
            "confidence": ["High", "High", "High"],
        }
    )

    coverage = calibration_coverage_truth(matched)

    assert coverage["scored_rows"] == 3
    assert coverage["coverage"] == pytest.approx(2 / 3, abs=1e-4)


def test_expected_misprep_cost_prefers_the_quantile_buffer() -> None:
    """When stockouts cost more than waste, a higher prep loses less money."""

    history = _weekly_sweet_history()
    dates = pd.date_range("2026-01-03", periods=6, freq="7D").date
    matched = pd.DataFrame(
        {
            "date": [dates[4], dates[5]],
            "category": ["sweet", "sweet"],
            "recommended_prep": [50, 52],
            "service_quantile": [0.78, 0.78],
            "true_demand": [55, 58],
            "sold_out": [True, True],
        }
    )
    economics = {"sweet": (3.2, 0.9)}  # (under_cost, over_cost)

    cost = expected_misprep_cost(matched, history, economics, demand_col="true_demand")

    # model: 3.2*5 + 3.2*6 = 35.2 over 2 days -> 17.6/day
    assert cost["dates"] == 2
    assert cost["demand_basis"] == "true_demand"
    assert cost["model_cost_per_day"] == pytest.approx(17.6)
    # last-week prep ceil(46),ceil(48): 3.2*9 + 3.2*10 = 60.8 -> 30.4/day
    assert cost["last_week_cost_per_day"] == pytest.approx(30.4)
    assert cost["best_baseline_cost_per_day"] == pytest.approx(30.4)
    assert cost["savings_per_day_vs_best"] == pytest.approx(12.8)
    assert cost["beats_baselines"] is True


def test_expected_misprep_cost_handles_empty_inputs() -> None:
    """Empty matched data or missing economics must not crash."""

    empty = expected_misprep_cost(pd.DataFrame(), _weekly_sweet_history(), {}, demand_col="sold")
    assert empty["beats_baselines"] is None
    assert empty["model_cost_per_day"] is None
