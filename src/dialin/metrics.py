"""Honest model-quality metrics: pinball loss, naive baselines, and calibration.

These implement the PRD section 6.1 evaluation contract: the model is judged on
quantile (pinball) loss against two naive baselines and on whether its stated
demand range is calibrated. All evaluation uses uncensored days only, because on
sold-out days true demand is unknown; the censored share is always reported
alongside the result instead of being hidden.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

BASELINE_LAG_DAYS = 7
TRAILING_BASELINE_WEEKS = 4


def pinball_loss(actual: float, forecast: float, quantile: float) -> float:
    """Return the quantile (pinball) loss for one forecast at one quantile."""

    if not 0 < quantile < 1:
        raise ValueError("quantile must be between 0 and 1")
    error = actual - forecast
    if error >= 0:
        return quantile * error
    return (quantile - 1) * error


def naive_baseline_forecasts(category_frame: pd.DataFrame) -> pd.DataFrame:
    """Return per date-category naive forecasts from raw sold history.

    Adds two columns: ``last_week_sold`` (same weekday, seven days earlier) and
    ``trailing_4wk_sold`` (mean of the four prior same-weekday sold values).
    Missing history yields NaN; callers drop those rows before scoring.
    """

    if category_frame.empty:
        return pd.DataFrame(
            columns=["date", "category", "last_week_sold", "trailing_4wk_sold"]
        )
    frame = category_frame[["date", "category", "sold"]].copy()
    frame["date"] = pd.to_datetime(frame["date"])
    frame = frame.sort_values(["category", "date"]).reset_index(drop=True)

    lookup = {
        (str(row["category"]), row["date"]): float(row["sold"])
        for _, row in frame.iterrows()
    }
    last_week: list[float | None] = []
    trailing: list[float | None] = []
    for _, row in frame.iterrows():
        category = str(row["category"])
        lags = [
            lookup.get((category, row["date"] - pd.Timedelta(days=BASELINE_LAG_DAYS * week)))
            for week in range(1, TRAILING_BASELINE_WEEKS + 1)
        ]
        last_week.append(lags[0])
        observed = [value for value in lags if value is not None]
        trailing.append(sum(observed) / len(observed) if observed else None)
    frame["last_week_sold"] = pd.array(last_week, dtype="Float64")
    frame["trailing_4wk_sold"] = pd.array(trailing, dtype="Float64")
    return frame[["date", "category", "last_week_sold", "trailing_4wk_sold"]]


def evaluate_model_vs_baselines(
    matched: pd.DataFrame,
    category_history: pd.DataFrame,
) -> dict[str, Any]:
    """Score the model against both naive baselines on held-out pinball loss.

    ``matched`` needs date, category, recommended_prep, service_quantile, sold,
    and sold_out columns (one row per recommendation with an observed closeout).
    ``category_history`` is the raw daily_category_metrics history used to build
    the baselines. Only uncensored rows with available baselines are scored.
    """

    empty: dict[str, Any] = {
        "evaluated_rows": 0,
        "censored_rows": 0,
        "censored_share": 0.0,
        "model_pinball": None,
        "last_week_pinball": None,
        "trailing_pinball": None,
        "beats_last_week": None,
        "beats_trailing": None,
        "beats_baselines": None,
    }
    if matched.empty:
        return empty

    frame = matched.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    censored_rows = int(frame["sold_out"].astype(bool).sum())
    censored_share = censored_rows / len(frame)
    frame = frame[~frame["sold_out"].astype(bool)]

    baselines = naive_baseline_forecasts(category_history)
    frame = frame.merge(baselines, on=["date", "category"], how="left")
    frame = frame.dropna(subset=["last_week_sold", "trailing_4wk_sold"])
    if frame.empty:
        empty["censored_rows"] = censored_rows
        empty["censored_share"] = round(censored_share, 4)
        return empty

    def mean_loss(forecast_column: str) -> float:
        losses = [
            pinball_loss(
                float(row["sold"]),
                float(row[forecast_column]),
                float(row["service_quantile"]),
            )
            for _, row in frame.iterrows()
        ]
        return sum(losses) / len(losses)

    model = mean_loss("recommended_prep")
    last_week = mean_loss("last_week_sold")
    trailing = mean_loss("trailing_4wk_sold")
    return {
        "evaluated_rows": len(frame),
        "censored_rows": censored_rows,
        "censored_share": round(censored_share, 4),
        "model_pinball": round(model, 4),
        "last_week_pinball": round(last_week, 4),
        "trailing_pinball": round(trailing, 4),
        "beats_last_week": model < last_week,
        "beats_trailing": model < trailing,
        "beats_baselines": model < last_week and model < trailing,
    }


def calibration_coverage(matched: pd.DataFrame) -> dict[str, Any]:
    """Return how often the stated demand range contained realised sales.

    Coverage is computed on uncensored rows only: on a sold-out day the true
    demand is at least ``prepared`` but otherwise unknown, so it can neither
    confirm nor refute the range. The censored share is reported so the
    exclusion is visible rather than silent.
    """

    if matched.empty:
        return {
            "uncensored_rows": 0,
            "censored_rows": 0,
            "censored_share": 0.0,
            "coverage": None,
            "by_confidence": {},
        }
    frame = matched.copy()
    censored_rows = int(frame["sold_out"].astype(bool).sum())
    censored_share = censored_rows / len(frame)
    frame = frame[~frame["sold_out"].astype(bool)].copy()
    if frame.empty:
        return {
            "uncensored_rows": 0,
            "censored_rows": censored_rows,
            "censored_share": round(censored_share, 4),
            "coverage": None,
            "by_confidence": {},
        }
    frame["covered"] = (frame["sold"] >= frame["demand_p_lower"]) & (
        frame["sold"] <= frame["demand_p_upper"]
    )
    by_confidence: dict[str, dict[str, Any]] = {}
    for label, group in frame.groupby("confidence"):
        by_confidence[str(label)] = {
            "rows": len(group),
            "coverage": round(float(group["covered"].mean()), 4),
        }
    return {
        "uncensored_rows": len(frame),
        "censored_rows": censored_rows,
        "censored_share": round(censored_share, 4),
        "coverage": round(float(frame["covered"].mean()), 4),
        "by_confidence": by_confidence,
    }
