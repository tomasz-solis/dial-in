"""How it's doing tab: honest model quality and observed proxies."""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from dialin import charts
from dialin import ui_components as ui
from dialin.demo_freshness import is_demo_location
from dialin.formatting import (
    format_adherence,
    format_percent,
)
from dialin.metrics import (
    calibration_coverage,
    calibration_coverage_truth,
    daily_operations_health,
    evaluate_against_truth,
    evaluate_model_vs_baselines,
    expected_misprep_cost,
    model_gate_report,
    onboarding_readiness,
    probe_diagnostics,
    suspicious_operational_jumps,
)
from dialin.pilot_report import build_pilot_report_markdown
from dialin.streamlit_cache import (
    PerformancePayload,
    fetch_performance_payload,
    load_truth_demand,
)

PLOTLY_CONFIG: dict[str, bool] = {"displayModeBar": False, "responsive": True}


def render(database_url: str, account_id: str, location_id: str) -> None:
    """Render the How-it's-doing tab: model quality, proxies, and corrections."""

    st.subheader("Performance")
    st.caption(
        "Start with the owner summary. Open Advanced when you need model diagnostics, data "
        "quality, or the pilot report."
    )
    load_key = f"load_performance:{account_id}:{location_id}"
    if st.button("Load performance", type="primary", key=f"{load_key}:button"):
        st.session_state[load_key] = True
    if st.session_state.get(load_key) is not True:
        st.info("Load performance when you want the owner summary or advanced analysis.")
        return

    payload = fetch_performance_payload(database_url, account_id, location_id)
    view = st.radio(
        "Performance view",
        ("Owner summary", "Advanced analysis"),
        horizontal=True,
        key=f"performance_view:{account_id}:{location_id}",
    )
    if view == "Owner summary":
        _render_owner_summary(payload)
        return

    _render_accuracy_tab(payload, account_id, location_id)
    _render_pilot_report(payload, account_id, location_id)
    _render_correction_audit(payload["corrections"])


def _render_owner_summary(payload: PerformancePayload) -> None:
    """Render the owner-first business readout without model jargon."""

    card = payload["scorecard"]
    matched = pd.DataFrame(payload["outcomes"])
    history = payload["frames"].get("daily_category_metrics", pd.DataFrame())
    if "input_source" in history.columns:
        history = history[history["input_source"] != "imputed"]
    economics = _economics_costs_from_rows(payload["economics"])
    cost = expected_misprep_cost(
        matched,
        history,
        economics,
        demand_col="sold",
        exclude_censored=True,
    )
    health = daily_operations_health(
        payload["frames"].get("daily_metrics", pd.DataFrame()),
        history,
        pd.DataFrame(card.get("rows", [])),
        pd.DataFrame(payload["recent_imports"]),
    )

    st.markdown("### Owner summary")
    title, body, tone = _owner_verdict(cost)
    getattr(st, tone)(f"**{title}**  \n{body}")

    readiness = onboarding_readiness(
        economics_rows=payload["economics"], health=health, cost=cost
    )
    if readiness["stage"] != "verdict_ready":
        _render_readiness(readiness)

    st.markdown(
        ui.card_grid(
            (
                ui.proof_card(
                    "Estimated margin protected",
                    _owner_savings_value(cost),
                    _owner_savings_caption(cost),
                ),
                ui.proof_card(
                    "Dial In prep misses",
                    _eur_per_day(cost.get("model_cost_per_day")),
                    "Estimated waste plus missed margin per open day.",
                ),
                ui.proof_card(
                    "Simple-rule prep misses",
                    _eur_per_day(cost.get("best_baseline_cost_per_day")),
                    "Better of last week and the four-week average.",
                ),
                ui.proof_card(
                    "Evidence",
                    f"{int(cost.get('dates') or 0)} open days",
                    f"{int(cost.get('excluded_censored_rows') or 0)} sold-out rows excluded.",
                ),
            )
        ),
        unsafe_allow_html=True,
    )

    next_title, next_body = _owner_next_action(payload, health, cost)
    st.markdown("#### What to do next")
    st.info(f"**{next_title}**  \n{next_body}")

    if cost.get("model_cost_per_day") is not None:
        left, right = st.columns(2, gap="large")
        with left:
            st.markdown("#### Estimated cost of prep misses")
            st.caption("Lower is better. This combines leftover cost and estimated missed margin.")
            st.plotly_chart(
                charts.cost_comparison_figure(cost),
                width="stretch",
                config=PLOTLY_CONFIG,
                key="owner_cost_comparison",
            )
        with right:
            st.markdown("#### Leftovers proxy")
            st.caption(
                "Prepared minus sold. Lower can be good, but not if it comes from selling out."
            )
            st.plotly_chart(
                _waste_comparison_chart(card),
                width="stretch",
                config=PLOTLY_CONFIG,
                key="owner_waste_comparison",
            )

    st.markdown(
        ui.card_grid(
            (
                ui.proof_card(
                    "Sellout rows",
                    str(int(card.get("actual_sellouts", 0))),
                    "True demand may be higher than recorded sales.",
                ),
                ui.proof_card(
                    "Recommendation followed",
                    _owner_adherence_value(card),
                    "Followed and overridden category decisions.",
                ),
                ui.proof_card(
                    "Missing closeouts",
                    _optional_percent(health.get("missing_closeout_rate")),
                    "Keep this low so the comparison stays credible.",
                ),
            )
        ),
        unsafe_allow_html=True,
    )

    with st.expander("How to read this summary"):
        st.markdown(
            "- **Estimated margin protected** is a modelled comparison, not accounting profit.\n"
            "- The **95% interval** describes uncertainty in the average gain, not the range "
            "expected on an individual day.\n"
            "- **Lower prep-miss cost is better**, provided sellouts do not rise.\n"
            "- Sold-out rows are excluded from the euro comparison because true demand is hidden.\n"
            "- Treat fewer than 28 open days as early evidence, not a business verdict."
        )


_READINESS_GLYPHS = {"done": "✓", "in_progress": "→", "todo": "•"}
_READINESS_STATUS_TEXT = {"done": "Done", "in_progress": "In progress", "todo": "To do"}


def _render_readiness(readiness: dict[str, Any]) -> None:
    """Render the pre-verdict onboarding progress panel for the first weeks.

    Turns the "not enough evidence yet" period into visible momentum: a progress
    bar toward the evidence threshold plus the observed leading-indicator steps.
    """

    percent = int(readiness["percent_to_verdict"])
    days = int(readiness["evidence_days"])
    target = int(readiness["evidence_target_days"])
    st.markdown("#### Getting to a verdict")
    st.caption(
        "A credible euro verdict needs clean economics and enough clean open days. This is the "
        "observed progress toward it — not a business result yet."
    )
    st.progress(
        percent / 100,
        text=f"{readiness['stage_label']} · {days} of {target} clean open days · {percent}%",
    )
    st.markdown(
        ui.card_grid(
            tuple(
                ui.proof_card(
                    step["label"],
                    f"{_READINESS_GLYPHS.get(step['status'], '•')} "
                    f"{_READINESS_STATUS_TEXT.get(step['status'], step['status'])}",
                    step["detail"],
                )
                for step in readiness["steps"]
            ),
        ),
        unsafe_allow_html=True,
    )
    next_step = readiness.get("next_step")
    if next_step is not None:
        st.info(f"**Next: {next_step['label']}**  \n{next_step['detail']}")


def _owner_verdict(cost: dict[str, Any]) -> tuple[str, str, str]:
    """Return a plain-language owner verdict and Streamlit message tone."""

    dates = int(cost.get("dates") or 0)
    savings = cost.get("savings_per_day_vs_best")
    if savings is None or dates == 0:
        return "Not enough evidence yet", "Keep recording clean closeouts.", "info"
    if dates < 28:
        return (
            "Early signal only",
            f"The comparison has {dates} open days; wait for at least 28 before judging it.",
            "info",
        )
    if float(savings) > 0:
        if cost.get("savings_robust") is False:
            return (
                "Early positive signal",
                f"Prep-miss cost is €{float(savings):.2f}/open day lower than the better simple "
                "rule, but its approximate 95% interval still includes zero — keep collecting "
                "evidence.",
                "info",
            )
        return (
            "Dial In looks promising",
            f"Estimated prep-miss cost is €{float(savings):.2f} lower per open day than the "
            "better simple rule, and its approximate 95% interval stays above zero.",
            "success",
        )
    return (
        "Dial In is not earning its keep yet",
        f"Estimated prep-miss cost is €{abs(float(savings)):.2f} higher per open day than the "
        "better simple rule.",
        "warning",
    )


def _owner_savings_value(cost: dict[str, Any]) -> str:
    """Format the modelled daily savings difference for an owner."""

    value = cost.get("savings_per_day_vs_best")
    if value is None:
        return "Not enough data"
    sign = "+" if float(value) > 0 else ""
    return f"{sign}€{float(value):.2f}/open day"


def _owner_savings_caption(cost: dict[str, Any]) -> str:
    """Explain the modelled difference without confusing uncertainty with spread."""

    low = cost.get("savings_ci_low")
    high = cost.get("savings_ci_high")
    if low is None or high is None:
        return "Versus the better simple prep rule; modelled, not booked profit."
    return (
        f"Approx. 95% interval: €{float(low):.2f} to €{float(high):.2f}; "
        "modelled, not booked profit."
    )


def _owner_adherence_value(card: dict[str, Any]) -> str:
    """Format followed recommendations as a compact owner-facing ratio."""

    attributed = int(card.get("attributed_rows", 0))
    if attributed == 0:
        return "Not tracked yet"
    followed = int(card.get("adhered_rows", 0))
    return f"{followed}/{attributed} ({followed / attributed:.0%})"


def _owner_next_action(
    payload: PerformancePayload,
    health: dict[str, Any],
    cost: dict[str, Any],
) -> tuple[str, str]:
    """Return the highest-value next action for the owner summary."""

    if any(str(row.get("values_source", "default")) == "default" for row in payload["economics"]):
        return "Confirm costs and prices", "The euro estimate is only as good as the economics."
    missing = health.get("missing_closeout_rate")
    if missing is not None and float(missing) > 0.1:
        return "Close the data gaps", "Complete daily closeouts before judging performance."
    if int(cost.get("dates") or 0) < 28:
        return (
            "Keep it advisory",
            "Collect at least 28 clean open days before acting on the result.",
        )
    if cost.get("beats_baselines") is not True:
        return "Review the weak categories", "Advanced analysis shows where Dial In trails."
    if cost.get("savings_robust") is not True:
        return (
            "Keep collecting evidence",
            "The estimated gain's approximate 95% interval still includes zero.",
        )
    return (
        "Protect the gain",
        "Keep tracking sellouts and overrides while using the recommendation.",
    )


def _render_pilot_report(
    payload: PerformancePayload,
    account_id: str,
    location_id: str,
) -> None:
    """Render the downloadable pilot report (Phase 12)."""

    matched = pd.DataFrame(payload["outcomes"])
    history = payload["frames"].get("daily_category_metrics", pd.DataFrame())
    if "input_source" in history.columns:
        history = history[history["input_source"] != "imputed"]
    economics = _economics_costs_from_rows(payload["economics"])
    gates = model_gate_report(matched, history, economics) if not matched.empty else []
    report_md = build_pilot_report_markdown(
        account_label=account_id,
        location_label=location_id,
        generated_on=date.today(),
        windows=payload["pilot_windows"],
        profile=payload["pilot_profile"],
        gates=gates,
        scorecard_rows=payload["scorecard"]["rows"],
        synthetic=is_demo_location(account_id, location_id),
    )
    st.markdown("#### Pilot report")
    st.caption(
        "Bundle phase windows, model gates, and observed outcomes into one shareable, honest "
        "report. Define windows and the setup checklist on the Setup tab."
    )
    st.download_button(
        "Download pilot report (Markdown)",
        data=report_md,
        file_name=f"dialin-pilot-report-{account_id}-{date.today().isoformat()}.md",
        mime="text/markdown",
        key=f"pilot_report:{account_id}:{location_id}",
    )
    with st.expander("Preview pilot report"):
        st.markdown(report_md)


def _render_accuracy_tab(
    payload: PerformancePayload,
    account_id: str,
    location_id: str,
) -> None:
    """Render observed accuracy and business impact proxy charts."""

    card = payload["scorecard"]
    frame = _accuracy_frame(card["rows"])
    matched = pd.DataFrame(payload["outcomes"])
    frames = payload["frames"]
    history = frames.get("daily_category_metrics", pd.DataFrame())
    if "input_source" in history.columns:
        history = history[history["input_source"] != "imputed"]
    economics = _economics_costs_from_rows(payload["economics"])
    st.markdown("### Advanced analysis")
    st.caption(
        "These are observed proxies. Sold-out days hide true demand, so the app does not "
        "treat sales alone as full forecast accuracy."
    )
    _render_advanced_reading_guide()
    _render_operations_health(
        frames=frames,
        imports=pd.DataFrame(payload["recent_imports"]),
        card=card,
    )
    _render_model_quality(matched, history, economics, account_id, location_id)
    _render_scorecard_snapshot(card)

    if frame.empty:
        st.info("No matched recommendation and closeout rows are available yet.")
        return

    daily = _daily_accuracy_frame(frame)
    left, right = st.columns(2, gap="large")
    with left:
        st.markdown("#### Forecast error trend")
        st.caption(
            "Closer to zero is better. Above zero means the recommendation ran higher than "
            "sales; below zero means it ran lower. Look for a persistent direction, not one day."
        )
        st.plotly_chart(
            _rolling_error_chart(daily),
            width="stretch",
            config=PLOTLY_CONFIG,
            key="accuracy_rolling_error",
        )
    with right:
        st.markdown("#### Waste proxy")
        st.caption(
            "Prepared minus sold. Lower suggests fewer leftovers, but sold-out rows can hide "
            "missed demand and this is not confirmed physical waste."
        )
        st.plotly_chart(
            _waste_comparison_chart(card),
            width="stretch",
            config=PLOTLY_CONFIG,
            key="accuracy_waste_comparison",
        )

    lower_left, lower_right = st.columns(2, gap="large")
    with lower_left:
        st.markdown("#### Error by category")
        st.caption(
            "Bars far from zero need attention. Positive means prep ran high versus sales; "
            "negative means it ran low."
        )
        st.plotly_chart(
            _category_error_chart(frame),
            width="stretch",
            config=PLOTLY_CONFIG,
            key="accuracy_category_error",
        )
    with lower_right:
        st.markdown("#### Follow-through")
        st.caption(
            "Separates model performance from operator choice. Overrides are useful evidence, "
            "especially when a reason was recorded."
        )
        st.plotly_chart(
            _adherence_chart(frame),
            width="stretch",
            config=PLOTLY_CONFIG,
            key="accuracy_adherence",
        )

    st.markdown("#### Prep recommendation vs closeout")
    st.caption(
        "Compare recommended prep with actual prep and sales. A large gap between actual prep "
        "and the recommendation is an override; sold equal to prepared may be a hidden stockout."
    )
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


def _render_model_quality(
    matched: pd.DataFrame,
    history: pd.DataFrame,
    economics: dict[str, tuple[float, float]],
    account_id: str,
    location_id: str,
) -> None:
    """Render expected-cost, calibration, and baseline verdicts (PRD section 6.1/6.2)."""

    if matched.empty:
        return

    st.markdown("#### Is the model earning trust?")

    cost = expected_misprep_cost(
        matched,
        history,
        economics,
        demand_col="sold",
        exclude_censored=True,
    )
    _render_cost_cards(cost)
    st.caption(
        "These are modelled euros, not cash in the till. They estimate the money lost each open "
        "day to over-prep (wasted food) and under-prep (missed sales + the drink that rides "
        "along), comparing Dial In's prep against the cheaper of two simple same-weekday rules "
        "(last week, or the 4-week average). Computed from your category economics on "
        "uncensored days only. Sold-out rows are excluded because sales reveal only a lower "
        "bound on demand; the excluded share is shown alongside the model-quality readout."
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
        st.caption(
            "Target is roughly 75-85%. Lower means ranges are too narrow; much higher can mean "
            "they are too wide to be useful."
        )
    with quality_right:
        st.plotly_chart(
            charts.baseline_pinball_figure(evaluation),
            width="stretch",
            config=PLOTLY_CONFIG,
            key="model_quality_baselines",
        )
        st.caption(
            "Lower is better. Dial In must beat both simple rules on the same usable dates."
        )

    _render_truth_quality(matched, history, economics, account_id, location_id)
    _render_model_gates(matched, history, economics)


def _render_advanced_reading_guide() -> None:
    """Explain the advanced view before the diagnostic charts begin."""

    with st.expander("How to read the advanced analysis"):
        st.markdown(
            "1. **Start with expected cost:** lower is better, but it is modelled rather than "
            "booked profit.\n"
            "2. **Check the gate:** a category remains advisory until evidence, calibration, "
            "bias, censoring, and both baselines pass.\n"
            "3. **Read direction, not noise:** repeated positive or negative error matters more "
            "than one unusual day.\n"
            "4. **Check data health last:** missing closeouts, POS rejects, and frequent sellouts "
            "can make every performance chart less trustworthy."
        )


def _render_operations_health(
    frames: dict[str, pd.DataFrame],
    imports: pd.DataFrame,
    card: dict[str, Any],
) -> None:
    """Render daily operating health checks for data and workflow reliability."""

    health = daily_operations_health(
        frames.get("daily_metrics", pd.DataFrame()),
        frames.get("daily_category_metrics", pd.DataFrame()),
        pd.DataFrame(card.get("rows", [])),
        imports,
    )

    st.markdown("#### Daily operations health")
    st.markdown(
        ui.card_grid(
            (
                ui.proof_card(
                    "Missing closeouts",
                    _optional_percent(health.get("missing_closeout_rate")),
                    f"{health.get('open_days', 0)} open days checked.",
                ),
                ui.proof_card(
                    "Input corrections",
                    _optional_percent(health.get("input_correction_rate")),
                    "Corrected closeouts and category rows.",
                ),
                ui.proof_card(
                    "POS rejects",
                    _optional_percent(health.get("pos_import_rejection_rate")),
                    "Rejected rows in recent POS imports.",
                ),
                ui.proof_card(
                    "Sellout rows",
                    _optional_percent(health.get("sellout_rate")),
                    "Rows where true demand may be hidden.",
                ),
                ui.proof_card(
                    "Followed",
                    _optional_percent(health.get("adherence_rate")),
                    f"{health.get('attributed_rows', 0)} attributed recommendation rows.",
                ),
            )
        ),
        unsafe_allow_html=True,
    )

    jumps = suspicious_operational_jumps(
        frames.get("daily_metrics", pd.DataFrame()),
        frames.get("daily_category_metrics", pd.DataFrame()),
    )
    if not jumps.empty:
        with st.expander("Data quality watchlist"):
            st.dataframe(jumps.tail(20), hide_index=True, width="stretch")


def _render_model_gates(
    matched: pd.DataFrame,
    history: pd.DataFrame,
    economics: dict[str, tuple[float, float]],
) -> None:
    """Render shadow/live readiness by category."""

    gates = model_gate_report(matched, history, economics)
    if not gates:
        return
    st.markdown("#### Shadow/live gate")
    st.caption(
        "Categories stay advisory until held-out days, range coverage, bias, censoring, "
        "pinball loss, and expected cost all clear the gate."
    )
    display = pd.DataFrame(gates)
    for column in ("range_coverage", "censoring_rate"):
        if column in display:
            display[column] = display[column].map(
                lambda value: "" if pd.isna(value) else format_percent(float(value))
            )
    st.dataframe(display, hide_index=True, width="stretch")


def _economics_costs_from_rows(rows: list[dict[str, Any]]) -> dict[str, tuple[float, float]]:
    """Return per-category (under_cost, over_cost) from effective category economics rows."""

    costs: dict[str, tuple[float, float]] = {}
    for row in rows:
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
    _render_probe_panel(mt)
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


def _render_probe_panel(mt: pd.DataFrame) -> None:
    """Render the de-censoring probe summary against synthetic truth (demo only)."""

    probe = probe_diagnostics(mt)
    if probe["probe_days"] == 0:
        return
    st.markdown("#### De-censoring probe (demo only)")
    st.caption(
        "On a controlled share of low-risk days the app deliberately prepped a few units "
        "above the usual number to learn where demand really tops out (PRD section 12). "
        "Against synthetic truth we can show what that revealed; real cafés see only the "
        "bounded extra cost, disclosed in advance."
    )
    st.markdown(
        ui.card_grid(
            (
                ui.proof_card(
                    "Probe days",
                    str(probe["probe_days"]),
                    "Low-risk days the app tested a higher number.",
                ),
                ui.proof_card(
                    "Hidden demand revealed",
                    f"{probe['revealed_units']} units",
                    "True demand observed that a sold-out day would have hidden.",
                ),
                ui.proof_card(
                    "Bounded extra waste",
                    f"{probe['extra_waste']} units",
                    f"Cost side of learning, capped per probe day "
                    f"({probe['extra_units']} extra units prepped total).",
                ),
            )
        ),
        unsafe_allow_html=True,
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


def _optional_percent(value: Any) -> str:
    """Format a nullable percentage for proof cards."""

    if value is None:
        return "Not enough data"
    return format_percent(float(value))


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


def _render_correction_audit(rows: list[dict[str, Any]]) -> None:
    """Render recent data correction audit rows."""

    with st.expander("Data corrections"):
        if not rows:
            st.caption("No corrections recorded yet.")
            return
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
