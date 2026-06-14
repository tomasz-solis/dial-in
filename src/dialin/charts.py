"""Plotly chart builders for Dial In proof and service-flow views."""

from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

INK = "#111111"
MUTED = "#5f6673"
LINE = "#dfe4ea"
MINT = "#83d7c0"
GREEN = "#22a879"
GRAY = "#9ca3af"
RED = "#d24b3f"

# Shared Streamlit ``st.plotly_chart`` config: no toolbar, responsive sizing.
PLOTLY_CONFIG: dict[str, bool] = {"displayModeBar": False, "responsive": True}


def pressure_figure(
    curve: list[dict[str, Any]],
    title: str,
    stockout_windows: list[dict[str, Any]] | None = None,
) -> go.Figure:
    """Build expected service pressure with optional demand-at-risk overlays."""

    frame = pd.DataFrame(curve)
    fig = go.Figure()
    if not frame.empty:
        frame = _pressure_frame(frame)
        fig.add_trace(
            go.Scatter(
                x=frame["minutes"],
                y=frame["expected_drinks"],
                mode="lines",
                line={"color": INK, "width": 3},
                fill="tozeroy",
                fillcolor="rgba(131, 215, 192, 0.58)",
                customdata=frame[["time", "pressure_index"]],
                hovertemplate=(
                    "<b>%{customdata[0]}</b><br>"
                    "Expected drinks: %{y:.1f}<br>"
                    "Pressure index: %{customdata[1]:.0f}<extra></extra>"
                ),
                name="Expected drinks",
            )
        )
        _add_stockout_overlays(fig, frame, stockout_windows or [])
        fig.update_xaxes(
            tickmode="array",
            tickvals=frame["minutes"],
            ticktext=frame["time"],
        )
    return finish_figure(fig, title=title, height=300, y_title="Expected drinks")


def rolling_error_figure(daily: pd.DataFrame) -> go.Figure:
    """Build the rolling forecast-error proxy chart."""

    fig = go.Figure()
    if not daily.empty:
        fig.add_trace(
            go.Scatter(
                x=daily["date"],
                y=daily["rolling_error_proxy"],
                mode="lines+markers",
                line={"color": INK, "width": 3},
                marker={"size": 6, "color": INK},
                hovertemplate="<b>%{x|%b %-d}</b><br>Rolling error: %{y:.1f}<extra></extra>",
                name="Rolling error proxy",
            )
        )
    return finish_figure(fig, title="Rolling forecast error proxy", height=300)


def waste_comparison_figure(card: dict[str, Any]) -> go.Figure:
    """Build a waste-proxy comparison chart."""

    frame = pd.DataFrame(
        [
            {"scenario": "Actual prep", "units": int(card.get("actual_waste", 0))},
            {"scenario": "Dial In proxy", "units": int(card.get("dialin_waste_proxy", 0))},
        ]
    )
    fig = go.Figure(
        go.Bar(
            x=frame["scenario"],
            y=frame["units"],
            marker={"color": [INK, GREEN]},
            hovertemplate="<b>%{x}</b><br>Waste proxy: %{y}<extra></extra>",
            name="Waste proxy",
        )
    )
    return finish_figure(fig, title="Waste proxy comparison", height=300, y_title="Units")


def category_error_figure(frame: pd.DataFrame) -> go.Figure:
    """Build a horizontal bar chart for category-level error contribution."""

    category = (
        frame.groupby("category", as_index=False)
        .agg(error_proxy=("error_proxy", "mean"))
        .sort_values("error_proxy", ascending=True)
    )
    fig = go.Figure()
    if not category.empty:
        fig.add_trace(
            go.Bar(
                x=category["error_proxy"],
                y=category["category"],
                orientation="h",
                marker={"color": INK},
                hovertemplate="<b>%{y}</b><br>Average error: %{x:.1f}<extra></extra>",
                name="Average error proxy",
            )
        )
    return finish_figure(fig, title="Error proxy by category", height=280, x_title="Units")


def adherence_figure(frame: pd.DataFrame) -> go.Figure:
    """Build a chart of followed, overridden, and unattributed rows."""

    labels = frame["adhered"].map(_format_adherence)
    counts = labels.value_counts().reindex(["Followed", "Overridden", "Unattributed"]).fillna(0)
    fig = go.Figure(
        go.Bar(
            x=counts.index,
            y=counts.values,
            marker={"color": [GREEN, INK, GRAY]},
            hovertemplate="<b>%{x}</b><br>Rows: %{y}<extra></extra>",
            name="Rows",
        )
    )
    return finish_figure(fig, title="Recommendation follow-through", height=280, y_title="Rows")


def recommendation_vs_observed_figure(frame: pd.DataFrame) -> go.Figure:
    """Build readable category rows comparing recommendation, sold, and prepared units."""

    if frame.empty:
        return finish_figure(go.Figure(), title="Recommendation vs observed units", height=320)
    recent = _recent_recommendation_frame(frame)
    categories = _category_order(recent["category"])
    fig = make_subplots(
        rows=len(categories),
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.14 if len(categories) > 1 else 0.05,
        subplot_titles=categories,
    )
    series = (
        ("recommended", "Recommended", GREEN),
        ("sold", "Observed sold", INK),
        ("actual_prepared", "Actual prepared", GRAY),
    )
    for row_index, category in enumerate(categories, start=1):
        category_frame = recent[recent["category"] == category].sort_values("date")
        for column, label, color in series:
            fig.add_trace(
                go.Bar(
                    x=category_frame["date"],
                    y=category_frame[column],
                    marker={"color": color},
                    hovertemplate=(
                        f"<b>{category}</b><br>"
                        "%{x|%b %d}<br>"
                        f"{label}: %{{y}}<extra></extra>"
                    ),
                    legendgroup=label,
                    name=label,
                    showlegend=row_index == 1,
                ),
                row=row_index,
                col=1,
            )
    fig.update_layout(barmode="group")
    finished = finish_figure(
        fig,
        title="",
        height=max(500, 250 * len(categories)),
        y_title="Units",
    )
    finished.update_layout(
        legend={
            "orientation": "h",
            "x": 0,
            "xanchor": "left",
            "y": 1.12,
            "yanchor": "bottom",
            "itemwidth": 30,
        },
        margin={"l": 54, "r": 20, "t": 58, "b": 52},
    )
    for annotation in finished.layout.annotations:
        annotation.update(
            x=0,
            xanchor="left",
            align="left",
            font={"size": 15, "color": INK},
        )
    finished.update_xaxes(tickformat="%b %d", tickangle=0, nticks=8)
    return finished


def calibration_coverage_figure(calibration: dict[str, Any]) -> go.Figure:
    """Build coverage-by-confidence bars against the stated target band."""

    by_confidence = calibration.get("by_confidence", {})
    order = [label for label in ("Low", "Medium", "High") if label in by_confidence]
    fig = go.Figure()
    if order:
        coverages = [float(by_confidence[label]["coverage"]) * 100 for label in order]
        rows = [int(by_confidence[label]["rows"]) for label in order]
        fig.add_trace(
            go.Bar(
                x=order,
                y=coverages,
                marker={"color": GREEN},
                customdata=rows,
                hovertemplate=(
                    "<b>%{x} confidence</b><br>"
                    "Range contained sales: %{y:.0f}%<br>"
                    "Uncensored days: %{customdata}<extra></extra>"
                ),
                name="Coverage",
            )
        )
        fig.add_hline(
            y=80,
            line={"color": MUTED, "width": 2, "dash": "dash"},
            annotation_text="~80% target",
            annotation_font={"color": MUTED},
        )
    return finish_figure(
        fig,
        title="Range coverage by confidence label",
        height=280,
        y_title="% of days inside range",
    )


def baseline_pinball_figure(evaluation: dict[str, Any]) -> go.Figure:
    """Build the model-vs-naive-baselines pinball loss comparison."""

    losses = (
        ("Dial In", evaluation.get("model_pinball"), GREEN),
        ("Last week", evaluation.get("last_week_pinball"), INK),
        ("4-week avg", evaluation.get("trailing_pinball"), GRAY),
    )
    fig = go.Figure()
    plotted = [(label, value, color) for label, value, color in losses if value is not None]
    if plotted:
        fig.add_trace(
            go.Bar(
                x=[label for label, _, _ in plotted],
                y=[float(value) for _, value, _ in plotted],
                marker={"color": [color for _, _, color in plotted]},
                hovertemplate="<b>%{x}</b><br>Pinball loss: %{y:.2f}<extra></extra>",
                name="Pinball loss",
            )
        )
    return finish_figure(
        fig,
        title="Forecast quality vs naive baselines",
        height=280,
        y_title="Pinball loss (lower is better)",
    )


def cost_comparison_figure(cost: dict[str, Any]) -> go.Figure:
    """Build the expected mis-prep cost per open day: model vs naive-prep decisions."""

    bars = (
        ("Dial In", cost.get("model_cost_per_day"), GREEN),
        ("Prep last week", cost.get("last_week_cost_per_day"), INK),
        ("Prep 4-week avg", cost.get("trailing_cost_per_day"), GRAY),
    )
    fig = go.Figure()
    plotted = [(label, value, color) for label, value, color in bars if value is not None]
    if plotted:
        fig.add_trace(
            go.Bar(
                x=[label for label, _, _ in plotted],
                y=[float(value) for _, value, _ in plotted],
                marker={"color": [color for _, _, color in plotted]},
                hovertemplate="<b>%{x}</b><br>€%{y:.2f} per open day<extra></extra>",
                name="Expected cost",
            )
        )
    return finish_figure(
        fig,
        title="Expected mis-prep cost per day (lower is better)",
        height=280,
        y_title="Euro per open day",
    )


def finish_figure(
    fig: go.Figure,
    title: str,
    height: int,
    x_title: str | None = None,
    y_title: str | None = None,
) -> go.Figure:
    """Apply the shared Dial In Plotly theme."""

    fig.update_layout(
        title={"text": title, "font": {"size": 18, "color": INK}, "x": 0},
        height=height,
        margin={"l": 48, "r": 20, "t": 54, "b": 44},
        paper_bgcolor="rgba(255,255,255,0)",
        plot_bgcolor="rgba(255,255,255,0)",
        font={"family": "Inter, ui-sans-serif, system-ui, sans-serif", "color": INK},
        hoverlabel={"bgcolor": "#ffffff", "bordercolor": LINE, "font": {"color": INK}},
        showlegend=bool(fig.data and len(fig.data) > 1),
        legend={"orientation": "h", "y": -0.2, "x": 0},
    )
    fig.update_xaxes(
        title=x_title,
        showgrid=False,
        zeroline=False,
        linecolor=LINE,
        tickfont={"color": MUTED},
        title_font={"color": MUTED},
    )
    fig.update_yaxes(
        title=y_title,
        gridcolor=LINE,
        zeroline=False,
        linecolor=LINE,
        tickfont={"color": MUTED},
        title_font={"color": MUTED},
    )
    return fig


def _format_adherence(value: Any) -> str:
    """Format recommendation attribution for chart grouping."""

    if value is True:
        return "Followed"
    if value is False:
        return "Overridden"
    return "Unattributed"


def _pressure_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Return pressure rows with numeric clock minutes for overlays."""

    prepared = frame.copy()
    prepared["minutes"] = prepared["time"].map(_clock_minutes)
    return prepared.dropna(subset=["minutes"]).sort_values("minutes")


def _add_stockout_overlays(
    fig: go.Figure,
    frame: pd.DataFrame,
    stockout_windows: list[dict[str, Any]],
) -> None:
    """Add red demand-at-risk overlays for known sellout windows."""

    for index, window in enumerate(stockout_windows):
        start = _clock_minutes(window.get("start_time"))
        end = _clock_minutes(window.get("end_time")) or frame["minutes"].max()
        if start is None or end <= start:
            continue
        window_frame = _window_pressure_frame(frame, start, end)
        if window_frame.empty:
            continue
        category = str(window.get("category") or "Stockout")
        start_label = _clock_label(start)
        custom = pd.DataFrame(
            {
                "time": window_frame["minutes"].map(_clock_label),
                "category": category,
                "start": start_label,
            }
        )
        fig.add_trace(
            go.Scatter(
                x=window_frame["minutes"],
                y=window_frame["expected_drinks"],
                mode="lines",
                line={"color": RED, "width": 0},
                fill="tozeroy",
                fillcolor="rgba(210, 75, 63, 0.38)",
                customdata=custom[["time", "category", "start"]],
                hovertemplate=(
                    "<b>%{customdata[1]} sold out</b><br>"
                    "Last sale: %{customdata[2]}<br>"
                    "%{customdata[0]} expected drinks: %{y:.1f}<extra></extra>"
                ),
                name="Demand after sellout",
                legendgroup="Demand after sellout",
                showlegend=index == 0,
            )
        )
        fig.add_vline(
            x=start,
            line={"color": RED, "width": 2, "dash": "dash"},
            opacity=0.75,
        )


def _window_pressure_frame(frame: pd.DataFrame, start: float, end: float) -> pd.DataFrame:
    """Return pressure points clipped to a stockout window."""

    first = float(frame["minutes"].min())
    last = float(frame["minutes"].max())
    clipped_start = max(start, first)
    clipped_end = min(end, last)
    if clipped_end <= clipped_start:
        return pd.DataFrame()
    inside = frame[(frame["minutes"] > clipped_start) & (frame["minutes"] < clipped_end)]
    boundary = pd.DataFrame(
        [
            {
                "minutes": clipped_start,
                "expected_drinks": _interpolated_pressure(frame, clipped_start),
            },
            {
                "minutes": clipped_end,
                "expected_drinks": _interpolated_pressure(frame, clipped_end),
            },
        ]
    )
    return (
        pd.concat([boundary, inside[["minutes", "expected_drinks"]]], ignore_index=True)
        .sort_values("minutes")
        .drop_duplicates(subset=["minutes"])
    )


def _interpolated_pressure(frame: pd.DataFrame, minute: float) -> float:
    """Return linearly interpolated expected drinks at one clock minute."""

    ordered = frame.sort_values("minutes")
    before = ordered[ordered["minutes"] <= minute].tail(1)
    after = ordered[ordered["minutes"] >= minute].head(1)
    if before.empty:
        return float(after.iloc[0]["expected_drinks"])
    if after.empty:
        return float(before.iloc[0]["expected_drinks"])
    before_row = before.iloc[0]
    after_row = after.iloc[0]
    before_minute = float(before_row["minutes"])
    after_minute = float(after_row["minutes"])
    if after_minute == before_minute:
        return float(before_row["expected_drinks"])
    share = (minute - before_minute) / (after_minute - before_minute)
    before_value = float(before_row["expected_drinks"])
    after_value = float(after_row["expected_drinks"])
    return before_value + (after_value - before_value) * share


def _clock_minutes(value: Any) -> float | None:
    """Convert HH:MM-like values to minutes after midnight."""

    if value is None or pd.isna(value):
        return None
    if hasattr(value, "hour") and hasattr(value, "minute"):
        return float(int(value.hour) * 60 + int(value.minute))
    parts = str(value).strip().split(":")
    if len(parts) < 2:
        return None
    try:
        return float(int(parts[0]) * 60 + int(parts[1]))
    except ValueError:
        return None


def _clock_label(minutes: Any) -> str:
    """Format minutes after midnight as HH:MM."""

    minute_value = round(float(minutes))
    hour, minute = divmod(minute_value, 60)
    return f"{hour:02d}:{minute:02d}"


def _recent_recommendation_frame(frame: pd.DataFrame, max_dates: int = 14) -> pd.DataFrame:
    """Return the most recent dated recommendation rows for comparison charts."""

    sorted_frame = frame.sort_values(["date", "category"]).copy()
    recent_dates = sorted_frame["date"].drop_duplicates().tail(max_dates)
    return sorted_frame[sorted_frame["date"].isin(recent_dates)]


def _category_order(categories: pd.Series) -> list[str]:
    """Return a stable display order for category rows."""

    values = [str(value) for value in categories.dropna().unique()]
    preferred = [value for value in ("Sweet", "Savory") if value in values]
    remaining = sorted(value for value in values if value not in preferred)
    return [*preferred, *remaining]
