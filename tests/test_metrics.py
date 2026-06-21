"""Tests for honest model-quality metrics."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

import dialin.metrics as metrics
from dialin.metrics import (
    calibration_coverage,
    calibration_coverage_truth,
    daily_operations_health,
    evaluate_against_truth,
    evaluate_model_vs_baselines,
    expected_misprep_cost,
    model_gate_report,
    naive_baseline_forecasts,
    pinball_loss,
    suspicious_operational_jumps,
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
    assert empty["savings_std_error"] is None
    assert empty["savings_robust"] is None


def test_expected_misprep_cost_reports_savings_uncertainty() -> None:
    """Headline savings must carry uncertainty so a few lucky days are not a verdict."""

    # Ten same-weekday rows so the trailing-4wk baseline resolves on the last four.
    dates = pd.date_range("2026-01-03", periods=10, freq="7D").date
    history = pd.DataFrame(
        {
            "date": dates,
            "category": ["sweet"] * 10,
            "sold": [40, 41, 42, 43, 44, 45, 46, 47, 48, 49],
        }
    )
    # The model beats the baseline on every evaluated day, but by a different
    # margin each day, so the per-day savings has a real, non-zero spread.
    matched = pd.DataFrame(
        {
            "date": list(dates[6:10]),
            "category": ["sweet"] * 4,
            "recommended_prep": [55, 54, 60, 58],
            "service_quantile": [0.78] * 4,
            "true_demand": [72, 72, 72, 78],
            "sold_out": [True, True, True, True],
        }
    )
    economics = {"sweet": (3.2, 0.9)}

    cost = expected_misprep_cost(matched, history, economics, demand_col="true_demand")

    assert cost["dates"] == 4
    assert cost["savings_std_error"] is not None
    assert cost["savings_std_error"] > 0
    # A 95% interval is the mean plus/minus ~1.96 standard errors.
    assert cost["savings_ci_low"] == pytest.approx(
        cost["savings_per_day_vs_best"] - 1.96 * cost["savings_std_error"], abs=0.01
    )
    assert cost["savings_robust"] is (cost["savings_ci_low"] > 0)


def test_savings_standard_error_allows_for_serial_correlation() -> None:
    """Adjacent positive residuals should widen uncertainty versus an IID estimate."""

    values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]
    serial_error = metrics._standard_error(values)
    iid_error = metrics._standard_error(values, max_lag=0)

    assert serial_error is not None
    assert iid_error is not None
    assert serial_error > iid_error


def test_daily_operations_health_reports_data_path_rates() -> None:
    """Operator health should expose missing, corrected, rejected, censored, and followed rates."""

    daily = pd.DataFrame(
        {
            "date": [date(2026, 1, day) for day in (1, 2, 3)],
            "is_open": [True, True, False],
            "drinks_sold": [100, None, None],
            "input_source": ["confirmed", "imputed", "confirmed"],
        }
    )
    categories = pd.DataFrame(
        {
            "date": [date(2026, 1, 1), date(2026, 1, 2)],
            "category": ["sweet", "sweet"],
            "sold_out": [False, True],
            "input_source": ["confirmed", "corrected"],
        }
    )
    recommendations = pd.DataFrame({"adhered": [True, False, None]})
    imports = pd.DataFrame({"rows_imported": [9], "rows_rejected": [1]})

    health = daily_operations_health(daily, categories, recommendations, imports)

    assert health["missing_closeout_rate"] == pytest.approx(0.5)
    assert health["input_correction_rate"] == pytest.approx(0.25)
    assert health["pos_import_rejection_rate"] == pytest.approx(0.1)
    assert health["sellout_rate"] == pytest.approx(0.5)
    assert health["adherence_rate"] == pytest.approx(0.5)


def test_suspicious_operational_jumps_flags_large_changes() -> None:
    """Large same-metric jumps should land in the review queue."""

    daily = pd.DataFrame(
        {
            "date": [date(2026, 1, 1), date(2026, 1, 2)],
            "drinks_sold": [100, 200],
        }
    )
    categories = pd.DataFrame(
        {
            "date": [date(2026, 1, 1), date(2026, 1, 2)],
            "category": ["sweet", "sweet"],
            "sold": [20, 40],
            "prepared": [24, 25],
        }
    )

    jumps = suspicious_operational_jumps(daily, categories)

    assert set(jumps["field"]) == {"drinks_sold", "sold"}


def test_model_gate_report_starts_categories_in_shadow() -> None:
    """Thin held-out evidence should keep a category advisory even if the model is accurate."""

    history = _weekly_sweet_history()
    dates = pd.date_range("2026-01-03", periods=6, freq="7D").date
    matched = pd.DataFrame(
        {
            "date": [dates[4], dates[5]],
            "category": ["sweet", "sweet"],
            "recommended_prep": [48, 50],
            "demand_p50": [47, 49],
            "service_quantile": [0.78, 0.78],
            "sold": [48, 50],
            "sold_out": [False, False],
            "demand_p_lower": [44, 46],
            "demand_p_upper": [52, 54],
            "confidence": ["Medium", "Medium"],
        }
    )

    report = model_gate_report(matched, history, {"sweet": (3.2, 0.9)})

    assert report[0]["category"] == "sweet"
    assert report[0]["status"] == "shadow"
    assert report[0]["evaluated_days"] == 2
    assert report[0]["signed_error"] == pytest.approx(-1.0)


def test_observed_cost_excludes_censored_rows() -> None:
    """A sales cap must not be treated as realised demand in a money comparison."""

    history = _weekly_sweet_history()
    dates = pd.date_range("2026-01-03", periods=6, freq="7D").date
    matched = pd.DataFrame(
        {
            "date": [dates[4], dates[5]],
            "category": ["sweet", "sweet"],
            "recommended_prep": [50, 52],
            "sold": [48, 50],
            "sold_out": [False, True],
        }
    )

    cost = expected_misprep_cost(
        matched,
        history,
        {"sweet": (3.2, 0.9)},
        demand_col="sold",
        exclude_censored=True,
    )

    assert cost["rows"] == 1
    assert cost["dates"] == 1
    assert cost["excluded_censored_rows"] == 1


def test_model_gate_bias_uses_median_demand_not_buffered_prep() -> None:
    """Economic service-level buffer is intentional and must not count as forecast bias."""

    history = _weekly_sweet_history()
    dates = pd.date_range("2026-01-03", periods=6, freq="7D").date
    matched = pd.DataFrame(
        {
            "date": [dates[4], dates[5]],
            "category": ["sweet", "sweet"],
            "recommended_prep": [60, 62],
            "demand_p50": [48, 50],
            "service_quantile": [0.78, 0.78],
            "sold": [48, 50],
            "sold_out": [False, False],
            "demand_p_lower": [44, 46],
            "demand_p_upper": [52, 54],
            "confidence": ["Medium", "Medium"],
        }
    )

    report = model_gate_report(matched, history, {"sweet": (3.2, 0.9)})

    assert report[0]["signed_error"] == pytest.approx(0.0)
