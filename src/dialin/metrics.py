"""Honest model-quality metrics: pinball loss, naive baselines, calibration,
and expected mis-prep cost.

These implement the PRD section 6.1/6.2 evaluation contract. Two evaluation
lenses are provided on purpose:

* **Observed (production) lens** — scores against censored ``sold`` on uncensored
  days only, because on sold-out days true demand is unknown. Pinball loss on a
  censored sample is biased toward low point forecasts, so the honest headline
  for the observed lens is **expected mis-prep cost** (a decision-vs-decision
  money comparison), not pinball.
* **Ground-truth (demo) lens** — only possible with synthetic data, scores
  against ``true_demand`` on every day. This removes the censoring bias and
  shows the model's real skill.

The censored share is always reported alongside the observed lens rather than
hidden.
"""

from __future__ import annotations

import math
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


def _with_baselines(
    matched: pd.DataFrame,
    category_history: pd.DataFrame,
    *,
    exclude_censored: bool,
) -> tuple[pd.DataFrame, int, int]:
    """Merge naive baselines onto matched rows and return (frame, censored, total)."""

    frame = matched.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    total = len(frame)
    censored = int(frame["sold_out"].astype(bool).sum()) if "sold_out" in frame else 0
    if exclude_censored and "sold_out" in frame:
        frame = frame[~frame["sold_out"].astype(bool)]
    baselines = naive_baseline_forecasts(category_history)
    frame = frame.merge(baselines, on=["date", "category"], how="left")
    frame = frame.dropna(subset=["last_week_sold", "trailing_4wk_sold"])
    return frame, censored, total


def _mean_pinball(frame: pd.DataFrame, forecast_col: str, target_col: str) -> float:
    """Mean pinball loss of one forecast column against a target at each row's quantile."""

    losses = [
        pinball_loss(
            float(row[target_col]), float(row[forecast_col]), float(row["service_quantile"])
        )
        for _, row in frame.iterrows()
    ]
    return sum(losses) / len(losses)


def _evaluate(
    matched: pd.DataFrame,
    category_history: pd.DataFrame,
    *,
    target: str,
    exclude_censored: bool,
) -> dict[str, Any]:
    """Score the model against both naive baselines on pinball loss."""

    empty: dict[str, Any] = {
        "evaluated_rows": 0,
        "evaluated_dates": 0,
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

    frame, censored, total = _with_baselines(
        matched, category_history, exclude_censored=exclude_censored
    )
    censored_share = censored / total if total else 0.0
    if frame.empty:
        empty["censored_rows"] = censored
        empty["censored_share"] = round(censored_share, 4)
        return empty

    model = _mean_pinball(frame, "recommended_prep", target)
    last_week = _mean_pinball(frame, "last_week_sold", target)
    trailing = _mean_pinball(frame, "trailing_4wk_sold", target)
    return {
        "evaluated_rows": len(frame),
        "evaluated_dates": int(frame["date"].nunique()),
        "censored_rows": censored,
        "censored_share": round(censored_share, 4),
        "model_pinball": round(model, 4),
        "last_week_pinball": round(last_week, 4),
        "trailing_pinball": round(trailing, 4),
        "beats_last_week": model < last_week,
        "beats_trailing": model < trailing,
        "beats_baselines": model < last_week and model < trailing,
    }


def evaluate_model_vs_baselines(
    matched: pd.DataFrame,
    category_history: pd.DataFrame,
) -> dict[str, Any]:
    """Observed lens: pinball vs censored ``sold`` on uncensored days only.

    ``matched`` needs date, category, recommended_prep, service_quantile, sold,
    and sold_out columns. Only uncensored rows with available baselines are
    scored. See module docstring for why expected cost is the better headline.
    """

    return _evaluate(matched, category_history, target="sold", exclude_censored=True)


def evaluate_against_truth(
    matched: pd.DataFrame,
    category_history: pd.DataFrame,
) -> dict[str, Any]:
    """Ground-truth (demo) lens: pinball vs ``true_demand`` on every day.

    ``matched`` needs a ``true_demand`` column. No censoring exclusion applies
    because true demand is observable on sold-out days in synthetic data.
    """

    return _evaluate(matched, category_history, target="true_demand", exclude_censored=False)


def _coverage(matched: pd.DataFrame, *, target: str, exclude_censored: bool) -> dict[str, Any]:
    """Return how often the stated demand range contained the target demand."""

    base: dict[str, Any] = {
        "scored_rows": 0,
        "censored_rows": 0,
        "censored_share": 0.0,
        "coverage": None,
        "by_confidence": {},
    }
    if matched.empty:
        return base
    frame = matched.copy()
    total = len(frame)
    censored = int(frame["sold_out"].astype(bool).sum()) if "sold_out" in frame else 0
    if exclude_censored and "sold_out" in frame:
        frame = frame[~frame["sold_out"].astype(bool)].copy()
    base["censored_rows"] = censored
    base["censored_share"] = round(censored / total, 4) if total else 0.0
    if frame.empty:
        return base
    frame["covered"] = (frame[target] >= frame["demand_p_lower"]) & (
        frame[target] <= frame["demand_p_upper"]
    )
    by_confidence: dict[str, dict[str, Any]] = {}
    for label, group in frame.groupby("confidence"):
        by_confidence[str(label)] = {
            "rows": len(group),
            "coverage": round(float(group["covered"].mean()), 4),
        }
    base["scored_rows"] = len(frame)
    base["coverage"] = round(float(frame["covered"].mean()), 4)
    base["by_confidence"] = by_confidence
    return base


def calibration_coverage(matched: pd.DataFrame) -> dict[str, Any]:
    """Observed lens coverage: target ``sold`` on uncensored rows only.

    Censored days are excluded (true demand unknown) and their share reported.
    """

    result = _coverage(matched, target="sold", exclude_censored=True)
    # legacy key name kept for existing callers/tests
    result["uncensored_rows"] = result["scored_rows"]
    return result


def calibration_coverage_truth(matched: pd.DataFrame) -> dict[str, Any]:
    """Ground-truth (demo) coverage: target ``true_demand`` on every day."""

    return _coverage(matched, target="true_demand", exclude_censored=False)


def expected_misprep_cost(
    matched: pd.DataFrame,
    category_history: pd.DataFrame,
    economics: dict[str, tuple[float, float]],
    *,
    demand_col: str,
) -> dict[str, Any]:
    """Compare prep *decisions* by expected mis-prep cost (PRD section 6.2).

    For each row and method the cost is
    ``Co * max(prep - demand, 0) + Cu * max(demand - prep, 0)`` where ``(Cu, Co)``
    come from ``economics`` per category. This compares prep quantities directly
    in money, so it sidesteps the quantile mismatch that makes pinball unfair to
    a newsvendor forecaster. Baselines are turned into real prep decisions by
    rounding their point forecast up.

    With ``demand_col="sold"`` (observed lens) the cost on sold-out days uses
    censored sales, which *under*-counts stockout cost, so the model's reported
    advantage is a conservative lower bound. With ``demand_col="true_demand"``
    (demo lens) it is exact.
    """

    empty: dict[str, Any] = {
        "rows": 0,
        "dates": 0,
        "demand_basis": demand_col,
        "model_cost_per_day": None,
        "last_week_cost_per_day": None,
        "trailing_cost_per_day": None,
        "best_baseline_cost_per_day": None,
        "savings_per_day_vs_best": None,
        "beats_baselines": None,
    }
    if matched.empty or not economics:
        return empty
    frame, _, _ = _with_baselines(matched, category_history, exclude_censored=False)
    frame = frame[frame["category"].isin(economics)]
    frame = frame.dropna(subset=[demand_col])
    if frame.empty:
        return empty

    def row_cost(prep: float, demand: float, category: str) -> float:
        under_cost, over_cost = economics[category]
        return over_cost * max(prep - demand, 0.0) + under_cost * max(demand - prep, 0.0)

    totals = {"model": 0.0, "last_week": 0.0, "trailing": 0.0}
    for _, row in frame.iterrows():
        category = str(row["category"])
        demand = float(row[demand_col])
        totals["model"] += row_cost(float(row["recommended_prep"]), demand, category)
        totals["last_week"] += row_cost(math.ceil(float(row["last_week_sold"])), demand, category)
        totals["trailing"] += row_cost(math.ceil(float(row["trailing_4wk_sold"])), demand, category)

    n_dates = int(frame["date"].nunique())
    per_day = {key: value / n_dates for key, value in totals.items()}
    best_baseline = min(per_day["last_week"], per_day["trailing"])
    return {
        "rows": len(frame),
        "dates": n_dates,
        "demand_basis": demand_col,
        "model_cost_per_day": round(per_day["model"], 2),
        "last_week_cost_per_day": round(per_day["last_week"], 2),
        "trailing_cost_per_day": round(per_day["trailing"], 2),
        "best_baseline_cost_per_day": round(best_baseline, 2),
        "savings_per_day_vs_best": round(best_baseline - per_day["model"], 2),
        "beats_baselines": per_day["model"] < best_baseline,
    }
