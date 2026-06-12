"""Tests for Plotly chart builders."""

from __future__ import annotations

from datetime import date

import pandas as pd
import plotly.graph_objects as go

from dialin import charts


def test_pressure_figure_uses_single_area_trace() -> None:
    """Service pressure should render as one area trace with no second axis."""

    fig = charts.pressure_figure(
        [
            {"time": "08:00", "expected_drinks": 4.0, "pressure_index": 80},
            {"time": "08:30", "expected_drinks": 6.0, "pressure_index": 120},
        ],
        "Expected service pressure",
    )

    assert isinstance(fig, go.Figure)
    assert len(fig.data) == 1
    assert fig.data[0].type == "scatter"
    assert "yaxis2" not in fig.to_dict()["layout"]


def test_pressure_figure_overlays_demand_after_known_sellout() -> None:
    """Known sellout windows should appear on top of expected demand."""

    fig = charts.pressure_figure(
        [
            {"time": "12:00", "expected_drinks": 10.0, "pressure_index": 100},
            {"time": "12:30", "expected_drinks": 16.0, "pressure_index": 160},
            {"time": "13:00", "expected_drinks": 18.0, "pressure_index": 180},
            {"time": "13:30", "expected_drinks": 12.0, "pressure_index": 120},
        ],
        "Expected service pressure",
        stockout_windows=[
            {"category": "Sweet", "start_time": "12:20", "end_time": "13:30"},
        ],
    )

    assert len(fig.data) == 2
    assert fig.data[1].name == "Demand after sellout"
    assert fig.data[1].fillcolor == "rgba(210, 75, 63, 0.38)"
    assert min(fig.data[1].x) == 740
    assert max(fig.data[1].x) == 810
    assert fig.layout.shapes


def test_waste_comparison_figure_uses_bar_not_pie() -> None:
    """Waste comparison should stay in the chart vocabulary approved for the app."""

    fig = charts.waste_comparison_figure({"actual_waste": 18, "dialin_waste_proxy": 11})

    assert len(fig.data) == 1
    assert fig.data[0].type == "bar"


def test_recommendation_vs_observed_splits_category_rows() -> None:
    """Recommendation comparison should split categories into readable rows."""

    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(
                [
                    date(2026, 5, 31),
                    date(2026, 5, 31),
                    date(2026, 6, 1),
                    date(2026, 6, 1),
                ]
            ),
            "category": ["Sweet", "Savory", "Sweet", "Savory"],
            "recommended": [24, 18, 28, 20],
            "sold": [20, 16, 26, 19],
            "actual_prepared": [26, 18, 28, 21],
        }
    )

    fig = charts.recommendation_vs_observed_figure(frame)

    assert [trace.name for trace in fig.data[:3]] == [
        "Recommended",
        "Observed sold",
        "Actual prepared",
    ]
    assert len(fig.data) == 6
    assert all(trace.type == "bar" for trace in fig.data)
    assert [trace.showlegend for trace in fig.data] == [True, True, True, False, False, False]
    assert all("·" not in str(x_value) for trace in fig.data for x_value in trace.x)
    assert fig.layout.barmode == "group"
    assert fig.layout.height >= 500
    assert fig.layout.title.text == ""
    assert fig.layout.margin.t <= 60
    assert fig.layout.legend.y > 1.0
    assert all(annotation.x == 0 for annotation in fig.layout.annotations)


def test_adherence_figure_keeps_expected_status_order() -> None:
    """Follow-through charts should keep the same status order even with missing groups."""

    frame = pd.DataFrame({"adhered": [True, True, None]})

    fig = charts.adherence_figure(frame)

    assert list(fig.data[0].x) == ["Followed", "Overridden", "Unattributed"]


def test_calibration_coverage_figure_orders_confidence_labels() -> None:
    """Coverage bars should follow Low to High order with a target line."""

    fig = charts.calibration_coverage_figure(
        {
            "coverage": 0.79,
            "by_confidence": {
                "High": {"rows": 40, "coverage": 0.82},
                "Low": {"rows": 10, "coverage": 0.7},
            },
        }
    )

    assert len(fig.data) == 1
    assert list(fig.data[0].x) == ["Low", "High"]
    assert fig.data[0].y[0] == 70.0


def test_baseline_pinball_figure_skips_missing_losses() -> None:
    """Baseline comparison should only plot computed losses."""

    fig = charts.baseline_pinball_figure(
        {
            "model_pinball": 2.1,
            "last_week_pinball": 3.4,
            "trailing_pinball": None,
        }
    )

    assert len(fig.data) == 1
    assert list(fig.data[0].x) == ["Dial In", "Last week"]


def test_sellout_timing_figure_uses_single_bar_trace() -> None:
    """Known sellout timing should render as a simple bar chart."""

    frame = pd.DataFrame(
        {
            "category": ["Sweet"],
            "minutes_before_close": [90],
            "last_sale": ["11:30"],
            "severity_color": [charts.RED],
        }
    )

    fig = charts.sellout_timing_figure(frame)

    assert len(fig.data) == 1
    assert fig.data[0].type == "bar"
