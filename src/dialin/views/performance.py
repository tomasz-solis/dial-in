"""How it's doing tab: honest model quality and observed proxies."""

from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from dialin import charts
from dialin import ui_components as ui
from dialin.formatting import (
    format_adherence,
    format_percent,
)
from dialin.metrics import (
    calibration_coverage,
    calibration_coverage_truth,
    evaluate_against_truth,
    evaluate_model_vs_baselines,
    expected_misprep_cost,
)
from dialin.streamlit_cache import (
    fetch_category_economics,
    fetch_data_corrections,
    fetch_history_frames,
    fetch_recommendation_outcomes,
    load_truth_demand,
    scorecard,
)

PLOTLY_CONFIG: dict[str, bool] = {"displayModeBar": False, "responsive": True}


def render(database_url: str, account_id: str, location_id: str) -> None:
    """Render the How-it's-doing tab: model quality, proxies, and corrections."""

    st.subheader("Accuracy and business impact")
    st.caption(
        "This view loads matched recommendations, closeouts, baselines, and demo truth metrics."
    )
    load_key = f"load_performance:{account_id}:{location_id}"
    if st.button("Load analysis", type="primary", key=f"{load_key}:button"):
        st.session_state[load_key] = True
    if st.session_state.get(load_key) is not True:
        st.info("Load the analysis when you need the full model-quality readout.")
        return

    _render_accuracy_tab(database_url, account_id, location_id)
    _render_correction_audit(database_url, account_id, location_id)


def _render_accuracy_tab(database_url: str, account_id: str, location_id: str) -> None:
    """Render observed accuracy and business impact proxy charts."""

    card = scorecard(database_url, account_id, location_id)
    frame = _accuracy_frame(card["rows"])
    st.caption(
        "These are observed proxies. Sold-out days hide true demand, so the app does not "
        "treat sales alone as full forecast accuracy."
    )
    _render_model_quality(database_url, account_id, location_id)
    _render_scorecard_snapshot(card)

    if frame.empty:
        st.info("No matched recommendation and closeout rows are available yet.")
        return

    daily = _daily_accuracy_frame(frame)
    left, right = st.columns(2, gap="large")
    with left:
        st.markdown("#### Forecast error proxy is tracked over time")
        st.plotly_chart(
            _rolling_error_chart(daily),
            width="stretch",
            config=PLOTLY_CONFIG,
            key="accuracy_rolling_error",
        )
    with right:
        st.markdown("#### Waste proxy compares actual prep with Dial In")
        st.plotly_chart(
            _waste_comparison_chart(card),
            width="stretch",
            config=PLOTLY_CONFIG,
            key="accuracy_waste_comparison",
        )

    lower_left, lower_right = st.columns(2, gap="large")
    with lower_left:
        st.markdown("#### Category errors show where attention belongs")
        st.plotly_chart(
            _category_error_chart(frame),
            width="stretch",
            config=PLOTLY_CONFIG,
            key="accuracy_category_error",
        )
    with lower_right:
        st.markdown("#### Followed and overridden rows stay visible")
        st.plotly_chart(
            _adherence_chart(frame),
            width="stretch",
            config=PLOTLY_CONFIG,
            key="accuracy_adherence",
        )

    st.markdown("#### Recommendation vs observed closeout by category")
    st.plotly_chart(
        _recommendation_vs_observed_chart(frame),
        width="stretch",
        config=PLOTLY_CONFIG,
        key="accuracy_recommendation_vs_observed",
    )

    with st.expander("Matched recommendation rows"):
        st.dataframe(_accuracy_display_rows(frame).tail(25), hide_index=True, width="stretch")

    override_rows = _recent_override_rows(card["rows"])
    if override_rows:
        with st.expander("Recent overrides"):
            st.dataframe(pd.DataFrame(override_rows), hide_index=True, width="stretch")


def _render_model_quality(database_url: str, account_id: str, location_id: str) -> None:
    """Render expected-cost, calibration, and baseline verdicts (PRD section 6.1/6.2)."""

    outcomes = fetch_recommendation_outcomes(database_url, account_id, location_id)
    matched = pd.DataFrame(outcomes)
    if matched.empty:
        return
    history = fetch_history_frames(database_url, account_id, location_id)[
        "daily_category_metrics"
    ]
    if "input_source" in history.columns:
        history = history[history["input_source"] != "imputed"]
    economics = _economics_costs(database_url, account_id, location_id, matched)

    st.markdown("#### Is the model earning trust?")

    cost = expected_misprep_cost(matched, history, economics, demand_col="sold")
    _render_cost_cards(cost)
    st.caption(
        "These are modelled euros, not cash in the till. They estimate the money lost each open "
        "day to over-prep (wasted food) and under-prep (missed sales + the drink that rides "
        "along), comparing Dial In's prep against the cheaper of two simple same-weekday rules "
        "(last week, or the 4-week average). Computed from your category economics on observed "
        "sales, so sold-out days under-count missed sales — Dial In's edge here is a "
        "conservative lower bound."
    )
    st.plotly_chart(
        charts.cost_comparison_figure(cost),
        width="stretch",
        config=PLOTLY_CONFIG,
        key="model_quality_cost",
    )

    calibration = calibration_coverage(matched)
    evaluation = evaluate_model_vs_baselines(matched, history)
    st.markdown(
        ui.card_grid(
            (
                ui.proof_card(
                    "Range coverage",
                    _coverage_label(calibration),
                    _coverage_caption(calibration),
                ),
                ui.proof_card(
                    "Beats last-week baseline",
                    _verdict_label(evaluation.get("beats_last_week")),
                    _baseline_caption(evaluation, "last_week_pinball"),
                ),
                ui.proof_card(
                    "Beats 4-week baseline",
                    _verdict_label(evaluation.get("beats_trailing")),
                    _baseline_caption(evaluation, "trailing_pinball"),
                ),
            )
        ),
        unsafe_allow_html=True,
    )
    st.caption(
        "Calibration and pinball are scored on uncensored days only. Pinball against censored "
        "sales is biased toward low point forecasts, so treat it as a floor, not the verdict — "
        "the ground-truth panel below is the unbiased read."
    )
    quality_left, quality_right = st.columns(2, gap="large")
    with quality_left:
        st.plotly_chart(
            charts.calibration_coverage_figure(calibration),
            width="stretch",
            config=PLOTLY_CONFIG,
            key="model_quality_calibration",
        )
    with quality_right:
        st.plotly_chart(
            charts.baseline_pinball_figure(evaluation),
            width="stretch",
            config=PLOTLY_CONFIG,
            key="model_quality_baselines",
        )

    _render_truth_quality(matched, history, economics, account_id, location_id)


def _economics_costs(
    database_url: str,
    account_id: str,
    location_id: str,
    matched: pd.DataFrame,
) -> dict[str, tuple[float, float]]:
    """Return per-category (under_cost, over_cost) from effective category economics."""

    as_of = pd.to_datetime(matched["date"]).max().date()
    costs: dict[str, tuple[float, float]] = {}
    for row in fetch_category_economics(database_url, account_id, location_id, as_of):
        retail = float(row["retail_price"])
        cogs = float(row["unit_cogs"])
        salvage = float(row["salvage_share_default"])
        under_cost = retail - cogs + float(row["attach_and_balk_rate"]) * float(
            row["attached_drink_margin"]
        )
        over_cost = cogs * (1 - salvage)
        if under_cost > 0 and over_cost > 0:
            costs[str(row["category"])] = (under_cost, over_cost)
    return costs


def _render_cost_cards(cost: dict[str, Any]) -> None:
    """Render the expected mis-prep cost comparison cards."""

    st.markdown(
        ui.card_grid(
            (
                ui.proof_card(
                    "Beats a simple prep rule?",
                    _verdict_label(cost.get("beats_baselines")),
                    _savings_caption(cost),
                ),
                ui.proof_card(
                    "Dial In · lost to mis-prep",
                    _eur_per_day(cost.get("model_cost_per_day")),
                    "Modelled waste + missed sales per day.",
                ),
                ui.proof_card(
                    "Simple rule · lost to mis-prep",
                    _eur_per_day(cost.get("best_baseline_cost_per_day")),
                    "Cheaper of last-week / 4-week same-weekday prep.",
                ),
            )
        ),
        unsafe_allow_html=True,
    )


def _render_truth_quality(
    matched: pd.DataFrame,
    history: pd.DataFrame,
    economics: dict[str, tuple[float, float]],
    account_id: str,
    location_id: str,
) -> None:
    """Render the demo-only evaluation against synthetic ground-truth demand."""

    truth = load_truth_demand(account_id, location_id)
    if truth is None:
        return
    mt = matched.copy()
    mt["date"] = pd.to_datetime(mt["date"])
    mt = mt.merge(truth, on=["date", "category"], how="inner")
    if mt.empty:
        return

    coverage = calibration_coverage_truth(mt)
    evaluation = evaluate_against_truth(mt, history)
    cost = expected_misprep_cost(mt, history, economics, demand_col="true_demand")

    st.markdown("#### Measured against synthetic ground truth (demo only)")
    st.caption(
        "Synthetic data has a known true demand on every day, including sold-out days, so this "
        "is the unbiased read the observed metrics above cannot give. Real cafés have no truth "
        "file, so this panel only appears in the demo."
    )
    st.markdown(
        ui.card_grid(
            (
                ui.proof_card(
                    "Range coverage vs truth",
                    _coverage_label(coverage),
                    _truth_coverage_caption(coverage),
                ),
                ui.proof_card(
                    "Beats last-week (truth)",
                    _verdict_label(evaluation.get("beats_last_week")),
                    _baseline_caption(evaluation, "last_week_pinball"),
                ),
                ui.proof_card(
                    "Beats 4-week (truth)",
                    _verdict_label(evaluation.get("beats_trailing")),
                    _baseline_caption(evaluation, "trailing_pinball"),
                ),
            )
        ),
        unsafe_allow_html=True,
    )
    _render_cost_cards(cost)
    truth_left, truth_right = st.columns(2, gap="large")
    with truth_left:
        st.plotly_chart(
            charts.baseline_pinball_figure(evaluation),
            width="stretch",
            config=PLOTLY_CONFIG,
            key="truth_quality_baselines",
        )
    with truth_right:
        st.plotly_chart(
            charts.cost_comparison_figure(cost),
            width="stretch",
            config=PLOTLY_CONFIG,
            key="truth_quality_cost",
        )


def _truth_coverage_caption(coverage: dict[str, Any]) -> str:
    """Return the ground-truth coverage caption (all days, no censoring exclusion)."""

    return (
        f"Target ~80% · {int(coverage.get('scored_rows', 0))} days scored against "
        "true demand, censored or not."
    )


def _savings_caption(cost: dict[str, Any]) -> str:
    """State how much less Dial In loses than the simple rule — a modelled estimate."""

    savings = cost.get("savings_per_day_vs_best")
    days = int(cost.get("dates") or 0)
    if savings is None:
        return "Modelled estimate, not cash."
    if savings > 0:
        return f"Loses €{float(savings):.2f}/day less over {days} days — modelled, not cash."
    if savings < 0:
        return f"Loses €{-float(savings):.2f}/day more than the simple rule."
    return f"About even with the simple rule over {days} days."


def _eur_per_day(value: Any) -> str:
    """Format a euro-per-day amount for proof cards."""

    if value is None:
        return "Not enough data"
    return f"€{float(value):.2f}/day"


def _coverage_label(calibration: dict[str, Any]) -> str:
    """Return the headline calibration coverage value."""

    coverage = calibration.get("coverage")
    if coverage is None:
        return "Not enough data"
    return format_percent(float(coverage))


def _coverage_caption(calibration: dict[str, Any]) -> str:
    """Return the calibration caption with the censoring exclusion made visible."""

    uncensored = int(calibration.get("uncensored_rows", 0))
    censored_share = float(calibration.get("censored_share", 0.0))
    return (
        f"Target ~80% · {uncensored} uncensored days · "
        f"{format_percent(censored_share)} of days sold out and are excluded."
    )


def _verdict_label(verdict: Any) -> str:
    """Return a plain yes/no verdict for a baseline comparison."""

    if verdict is None:
        return "Not enough data"
    return "Yes" if verdict else "Not yet"


def _baseline_caption(evaluation: dict[str, Any], baseline_key: str) -> str:
    """Return the pinball-loss caption for one baseline comparison card."""

    model = evaluation.get("model_pinball")
    baseline = evaluation.get(baseline_key)
    if model is None or baseline is None:
        return "Needs matched recommendation and closeout history."
    days = evaluation.get("evaluated_dates", evaluation.get("evaluated_rows"))
    return f"Pinball loss {model:.2f} vs {baseline:.2f} · {days} days."


def _render_scorecard_snapshot(card: dict[str, Any]) -> None:
    """Render high-level accuracy and business-impact proxy metrics."""

    summary = _scorecard_summary(card)
    st.markdown(
        ui.card_grid(
            (
                ui.proof_card(
                    "Observed rows",
                    summary["rows"],
                    "Recommendation and closeout rows.",
                ),
                ui.proof_card(
                    "Waste proxy delta",
                    summary["waste_delta_label"],
                    "Illustrative replay; both sides use censored sales — not a counterfactual.",
                ),
                ui.proof_card(
                    "Followed rate",
                    summary["followed_rate"],
                    "Rows within recommendation tolerance.",
                ),
            )
        ),
        unsafe_allow_html=True,
    )


def _scorecard_summary(card: dict[str, Any]) -> dict[str, str]:
    """Return formatted proof metrics from a repository scorecard."""

    actual_waste = int(card.get("actual_waste", 0))
    dialin_waste = int(card.get("dialin_waste_proxy", 0))
    delta = actual_waste - dialin_waste
    if delta > 0:
        waste_delta_label = f"{delta} fewer units"
    elif delta < 0:
        waste_delta_label = f"{abs(delta)} more units"
    else:
        waste_delta_label = "Even"

    attributed = int(card.get("attributed_rows", 0))
    adhered = int(card.get("adhered_rows", 0))
    followed_rate = "No attribution" if attributed == 0 else format_percent(adhered / attributed)
    return {
        "rows": str(len(card.get("rows", []))),
        "waste_delta_label": waste_delta_label,
        "followed_rate": followed_rate,
    }


def _accuracy_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """Return a typed DataFrame of matched recommendation and closeout rows."""

    records: list[dict[str, Any]] = []
    for row in rows:
        recommended = int(row["recommended_prep"])
        sold = int(row["sold"])
        actual_prepared = int(row["actual_prepared"])
        records.append(
            {
                "date": pd.Timestamp(row["date"]),
                "category": str(row["category"]).title(),
                "recommended": recommended,
                "sold": sold,
                "actual_prepared": actual_prepared,
                "actual_waste": max(actual_prepared - sold, 0),
                "dialin_waste_proxy": max(recommended - sold, 0),
                "error_proxy": abs(recommended - sold),
                "short_proxy": recommended < sold,
                "sold_out": bool(row["sold_out"]),
                "adhered": row.get("adhered"),
            }
        )
    return pd.DataFrame.from_records(records)


def _daily_accuracy_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Aggregate accuracy proxies by business date for trend charts."""

    if frame.empty:
        return frame
    daily = (
        frame.sort_values("date")
        .groupby("date", as_index=False)
        .agg(
            error_proxy=("error_proxy", "mean"),
            actual_waste=("actual_waste", "sum"),
            dialin_waste_proxy=("dialin_waste_proxy", "sum"),
            actual_sellouts=("sold_out", "sum"),
            dialin_short_proxy=("short_proxy", "sum"),
        )
    )
    daily["rolling_error_proxy"] = (
        daily["error_proxy"].rolling(window=14, min_periods=1).mean().round(2)
    )
    return daily


def _accuracy_display_rows(frame: pd.DataFrame) -> pd.DataFrame:
    """Return a compact table for matched recommendation rows."""

    display = frame.copy()
    display["date"] = display["date"].dt.date
    display["sold out"] = display["sold_out"].map(lambda value: "yes" if value else "no")
    display["followed"] = display["adhered"].map(format_adherence)
    return display[
        [
            "date",
            "category",
            "recommended",
            "sold",
            "actual_prepared",
            "error_proxy",
            "actual_waste",
            "dialin_waste_proxy",
            "sold out",
            "followed",
        ]
    ].rename(
        columns={
            "actual_prepared": "actual prepared",
            "error_proxy": "error proxy",
            "actual_waste": "actual waste",
            "dialin_waste_proxy": "Dial In waste proxy",
        }
    )


def _rolling_error_chart(daily: pd.DataFrame) -> go.Figure:
    """Build the rolling forecast-error proxy line chart."""

    return charts.rolling_error_figure(daily)


def _waste_comparison_chart(card: dict[str, Any]) -> go.Figure:
    """Build a bar chart comparing observed and recommendation waste proxies."""

    return charts.waste_comparison_figure(card)


def _category_error_chart(frame: pd.DataFrame) -> go.Figure:
    """Build a horizontal bar chart for category error contribution."""

    return charts.category_error_figure(frame)


def _adherence_chart(frame: pd.DataFrame) -> go.Figure:
    """Build a bar chart of followed, overridden, and unattributed rows."""

    return charts.adherence_figure(frame)


def _recommendation_vs_observed_chart(frame: pd.DataFrame) -> go.Figure:
    """Build the recommendation vs observed closeout chart."""

    return charts.recommendation_vs_observed_figure(frame)


def _recent_override_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return a small table of recent non-adhered recommendation rows."""

    override_rows = [
        {
            "date": row["date"],
            "category": row["category"],
            "recommended": row["recommended_prep"],
            "prepared": row["recommendation_prepared"] or row["actual_prepared"],
            "delta": row["override_delta"],
            "reason": row["override_reason"] or "",
        }
        for row in rows
        if row.get("adhered") is False
    ]
    return override_rows[-8:]


def _render_correction_audit(database_url: str, account_id: str, location_id: str) -> None:
    """Render recent data correction audit rows."""

    rows = fetch_data_corrections(database_url, account_id, location_id)
    with st.expander("Data corrections"):
        if not rows:
            st.caption("No corrections recorded yet.")
            return
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
