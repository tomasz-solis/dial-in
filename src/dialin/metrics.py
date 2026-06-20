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

# PRD section 6.4.3: a calibrated p10-p90 range contains realised demand about
# 75-85% of the time once enough held-out days exist. The live-ready gate also
# requires >= 28 evaluated days, so this band is only consulted with enough
# evidence; before that a category stays in shadow on the evidence check.
CALIBRATION_TARGET_LOW = 0.75
CALIBRATION_TARGET_HIGH = 0.85


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
    exclude_censored: bool = False,
) -> dict[str, Any]:
    """Compare prep *decisions* by expected mis-prep cost (PRD section 6.2).

    For each row and method the cost is
    ``Co * max(prep - demand, 0) + Cu * max(demand - prep, 0)`` where ``(Cu, Co)``
    come from ``economics`` per category. This compares prep quantities directly
    in money, so it sidesteps the quantile mismatch that makes pinball unfair to
    a newsvendor forecaster. Baselines are turned into real prep decisions by
    rounding their point forecast up.

    Set ``exclude_censored=True`` for the observed ``sold`` lens. A sold-out
    row only supplies a lower bound on demand, and treating that lower bound as
    realised demand can change the ordering between two prep decisions; it is
    not a defensible savings estimate. With ``demand_col="true_demand"`` (demo
    lens), censored rows can be included because latent demand is known.
    """

    empty: dict[str, Any] = {
        "rows": 0,
        "dates": 0,
        "excluded_censored_rows": 0,
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
    excluded_censored_rows = (
        int(matched["sold_out"].astype(bool).sum())
        if exclude_censored and "sold_out" in matched
        else 0
    )
    empty["excluded_censored_rows"] = excluded_censored_rows
    frame, _, _ = _with_baselines(
        matched,
        category_history,
        exclude_censored=exclude_censored,
    )
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
        "excluded_censored_rows": excluded_censored_rows,
        "demand_basis": demand_col,
        "model_cost_per_day": round(per_day["model"], 2),
        "last_week_cost_per_day": round(per_day["last_week"], 2),
        "trailing_cost_per_day": round(per_day["trailing"], 2),
        "best_baseline_cost_per_day": round(best_baseline, 2),
        "savings_per_day_vs_best": round(best_baseline - per_day["model"], 2),
        "beats_baselines": per_day["model"] < best_baseline,
    }


def daily_operations_health(
    daily_metrics: pd.DataFrame,
    category_metrics: pd.DataFrame,
    recommendation_rows: pd.DataFrame,
    pos_import_runs: pd.DataFrame,
) -> dict[str, Any]:
    """Return daily data-quality and workflow health metrics for operators."""

    open_daily = (
        daily_metrics[daily_metrics["is_open"].astype(bool)].copy()
        if not daily_metrics.empty and "is_open" in daily_metrics
        else pd.DataFrame()
    )
    open_days = len(open_daily)
    missing_days = (
        int((open_daily.get("input_source", pd.Series(dtype=str)) == "imputed").sum())
        if open_days
        else 0
    )
    corrected_days = (
        int((open_daily.get("input_source", pd.Series(dtype=str)) == "corrected").sum())
        if open_days
        else 0
    )
    category_rows = len(category_metrics) if not category_metrics.empty else 0
    corrected_category_rows = (
        int((category_metrics.get("input_source", pd.Series(dtype=str)) == "corrected").sum())
        if category_rows
        else 0
    )
    sellout_rows = (
        int(category_metrics["sold_out"].astype(bool).sum())
        if category_rows and "sold_out" in category_metrics
        else 0
    )
    attributed_rows = (
        int(recommendation_rows["adhered"].notna().sum())
        if not recommendation_rows.empty and "adhered" in recommendation_rows
        else 0
    )
    adhered_rows = (
        int((recommendation_rows["adhered"] == True).sum())  # noqa: E712
        if attributed_rows
        else 0
    )
    imported = (
        int(pos_import_runs["rows_imported"].sum())
        if not pos_import_runs.empty and "rows_imported" in pos_import_runs
        else 0
    )
    rejected = (
        int(pos_import_runs["rows_rejected"].sum())
        if not pos_import_runs.empty and "rows_rejected" in pos_import_runs
        else 0
    )
    return {
        "open_days": open_days,
        "missing_closeout_rate": missing_days / open_days if open_days else None,
        "input_correction_rate": (corrected_days + corrected_category_rows)
        / max(open_days + category_rows, 1),
        "pos_import_rejection_rate": rejected / max(imported + rejected, 1),
        "sellout_rate": sellout_rows / category_rows if category_rows else None,
        "adherence_rate": adhered_rows / attributed_rows if attributed_rows else None,
        "attributed_rows": attributed_rows,
    }


def suspicious_operational_jumps(
    daily_metrics: pd.DataFrame,
    category_metrics: pd.DataFrame,
    threshold: float = 0.6,
) -> pd.DataFrame:
    """Return dates with large same-category operational jumps worth reviewing."""

    rows: list[dict[str, Any]] = []
    if not daily_metrics.empty and {"date", "drinks_sold"}.issubset(daily_metrics.columns):
        daily = daily_metrics.sort_values("date").copy()
        daily["previous"] = daily["drinks_sold"].shift(1)
        for _, row in daily.dropna(subset=["drinks_sold", "previous"]).iterrows():
            previous = max(float(row["previous"]), 1.0)
            change = abs(float(row["drinks_sold"]) - previous) / previous
            if change >= threshold:
                rows.append(
                    {
                        "date": row["date"],
                        "category": "drinks",
                        "field": "drinks_sold",
                        "change": round(change, 3),
                    }
                )
    if not category_metrics.empty:
        for category, group in category_metrics.sort_values("date").groupby("category"):
            for field in ("sold", "prepared"):
                if field not in group:
                    continue
                series = group[["date", field]].copy()
                series["previous"] = series[field].shift(1)
                for _, row in series.dropna(subset=[field, "previous"]).iterrows():
                    previous = max(float(row["previous"]), 1.0)
                    change = abs(float(row[field]) - previous) / previous
                    if change >= threshold:
                        rows.append(
                            {
                                "date": row["date"],
                                "category": str(category),
                                "field": field,
                                "change": round(change, 3),
                            }
                        )
    return pd.DataFrame(rows)


def probe_diagnostics(matched: pd.DataFrame) -> dict[str, int]:
    """Summarize de-censoring probe activity and what it would reveal (demo lens).

    This is a counterfactual read: in the synthetic demo the closeout ``prepared``
    is fixed gut-prep, so we measure what the *probe recommendation* would reveal
    if followed. ``revealed_units`` needs ``true_demand`` (synthetic only): we
    compare demand observable at the probe prep level (``min(true, recommended)``)
    to demand observable without the lift (``min(true, recommended - extra)``).
    ``extra_waste`` is the bounded cost side: extra units that reveal nothing.
    """

    empty = {"probe_days": 0, "extra_units": 0, "revealed_units": 0, "extra_waste": 0}
    if matched.empty or "probe_active" not in matched.columns:
        return empty
    probe = matched[matched["probe_active"] == True].copy()  # noqa: E712
    if probe.empty:
        return empty
    extra = probe["probe_extra_units"].astype(float)
    result = {"probe_days": int(probe.shape[0]), "extra_units": int(extra.sum())}
    if {"true_demand", "recommended_prep"}.issubset(probe.columns):
        true_demand = probe["true_demand"].astype(float)
        recommended = probe["recommended_prep"].astype(float)
        observed_with = pd.concat([true_demand, recommended], axis=1).min(axis=1)
        observed_without = pd.concat([true_demand, recommended - extra], axis=1).min(axis=1)
        revealed = (observed_with - observed_without).clip(lower=0)
        result["revealed_units"] = int(revealed.sum())
        result["extra_waste"] = int((extra - revealed).clip(lower=0).sum())
    else:
        result["revealed_units"] = 0
        result["extra_waste"] = 0
    return result


def model_gate_report(
    matched: pd.DataFrame,
    category_history: pd.DataFrame,
    economics: dict[str, tuple[float, float]],
) -> list[dict[str, Any]]:
    """Return shadow/live gate diagnostics by category."""

    reports: list[dict[str, Any]] = []
    if matched.empty:
        return reports
    for category, group in matched.groupby("category"):
        history = category_history[category_history["category"] == category]
        evaluation = evaluate_model_vs_baselines(group, history)
        calibration = calibration_coverage(group)
        cost = expected_misprep_cost(
            group,
            history,
            economics,
            demand_col="sold",
            exclude_censored=True,
        )
        uncensored = (
            group[~group["sold_out"].astype(bool)]
            if "sold_out" in group
            else group
        )
        signed_error = (
            float((uncensored["demand_p50"] - uncensored["sold"]).mean())
            if not uncensored.empty and {"demand_p50", "sold"}.issubset(uncensored.columns)
            else float("nan")
        )
        enough_days = int(evaluation["evaluated_dates"]) >= 28
        calibrated = (
            calibration.get("coverage") is not None
            and CALIBRATION_TARGET_LOW <= float(calibration["coverage"]) <= CALIBRATION_TARGET_HIGH
        )
        low_censoring = float(evaluation.get("censored_share") or 0.0) <= 0.4
        unbiased = not math.isnan(signed_error) and abs(signed_error) <= max(
            float(uncensored["sold"].mean()) * 0.05,
            1.0,
        )
        beats = evaluation.get("beats_baselines") is True
        cost_positive = cost.get("beats_baselines") is True
        live_ready = all((enough_days, calibrated, low_censoring, unbiased, beats, cost_positive))
        reports.append(
            {
                "category": str(category),
                "status": "live-ready" if live_ready else "shadow",
                "evaluated_days": int(evaluation["evaluated_dates"]),
                "beats_baselines": beats,
                "range_coverage": calibration.get("coverage"),
                "signed_error": None if math.isnan(signed_error) else round(signed_error, 2),
                "censoring_rate": evaluation.get("censored_share"),
                "expected_cost_beats_baseline": cost_positive,
            }
        )
    return reports
