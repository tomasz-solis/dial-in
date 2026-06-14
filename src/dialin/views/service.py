"""Service tab: synthetic service-pressure shape and sellout evidence."""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd
import streamlit as st

from dialin import charts
from dialin import ui_components as ui
from dialin.formatting import (
    format_clock,
    format_minutes_before_close,
    format_service_window,
    format_source_label,
    minutes_from_clock,
)
from dialin.streamlit_cache import (
    fetch_intraday_demo,
)

PLOTLY_CONFIG: dict[str, bool] = {"displayModeBar": False, "responsive": True}


def render(
    database_url: str,
    account_id: str,
    location_id: str,
    closeout_date: date,
    target_date: date,
) -> None:
    """Render service-window pressure and sellout timing."""

    st.subheader("Service flow")
    selected_date = st.date_input("Service date", value=target_date)
    business_date = selected_date if isinstance(selected_date, date) else target_date
    flow = fetch_intraday_demo(database_url, account_id, location_id, business_date)
    hours = flow["hours"]

    _render_flow_metric_cards(
        service_window=format_service_window(hours),
        expected_drinks=int(flow["expected_drinks"]),
        traffic_source=format_source_label(flow["expected_source"]),
    )

    if not hours["is_open"]:
        st.info("This date is marked closed in the active hours plan.")
        return

    st.markdown("#### Demand pressure changes the value of a sellout")
    _render_demand_flow(
        curve=flow["curve"],
        sellouts=flow["sellouts"],
        close_time=hours.get("close_time"),
        title="Expected service pressure",
        key=f"service_pressure_{business_date.isoformat()}",
    )

    if business_date > closeout_date:
        st.caption(
            "Future sellout timing appears only when POS timestamps or manual stockout evidence "
            "exist. The chart does not infer a sellout from missing rows."
        )


def _render_flow_metric_cards(
    service_window: str,
    expected_drinks: int,
    traffic_source: str,
) -> None:
    """Render service-flow metrics without truncating long text."""

    metrics = (
        ("Service window", service_window, "di-flow-value"),
        ("Expected drinks", str(expected_drinks), "di-flow-value"),
        ("Traffic source", traffic_source, "di-flow-value di-flow-text"),
    )
    columns = st.columns(3, gap="medium")
    for column, (label, value, value_class) in zip(columns, metrics, strict=True):
        with column:
            st.markdown(
                ui.metric_card(label, value, tone="light").replace(
                    "di-metric-value",
                    value_class,
                ),
                unsafe_allow_html=True,
            )


def _render_demand_flow(
    curve: list[dict[str, Any]],
    sellouts: list[dict[str, Any]],
    close_time: Any,
    title: str,
    key: str,
) -> None:
    """Render demand pressure and sellout evidence as one coherent section."""

    sellout_rows = _intraday_sellout_rows(sellouts, close_time)
    if not curve and not sellout_rows:
        st.markdown(
            ui.empty_state_list(
                "No demand-flow evidence",
                (
                    "No service-pressure curve is available.",
                    "No sellout time is recorded for this date.",
                ),
            ),
            unsafe_allow_html=True,
        )
        return
    _render_pressure_chart(
        curve,
        title,
        key=key,
        stockout_windows=_stockout_windows(sellouts, close_time),
    )
    st.caption("Synthetic daypart shape from daily history — not live POS intraday data.")
    _render_sellout_snapshot(sellout_rows)


def _render_pressure_chart(
    curve: list[dict[str, Any]],
    title: str,
    key: str,
    stockout_windows: list[dict[str, Any]] | None = None,
) -> None:
    """Render a clean service-pressure chart from half-hour buckets."""

    if not curve:
        st.markdown(
            ui.empty_state("No pressure curve", "No service-pressure curve is available."),
            unsafe_allow_html=True,
        )
        return
    st.plotly_chart(
        charts.pressure_figure(curve, title, stockout_windows=stockout_windows),
        width="stretch",
        config=PLOTLY_CONFIG,
        key=key,
    )


def _render_sellout_snapshot(sellout_rows: list[dict[str, Any]]) -> None:
    """Render sellout timing evidence against the service window."""

    if sellout_rows:
        st.dataframe(pd.DataFrame(sellout_rows), hide_index=True, width="stretch")
        return
    st.markdown(
        ui.empty_state("No sellout timing", "No sellout time is recorded for this date."),
        unsafe_allow_html=True,
    )


def _stockout_windows(rows: list[dict[str, Any]], close_time: Any) -> list[dict[str, Any]]:
    """Return known stockout windows for pressure-chart overlays."""

    end_time = format_clock(close_time)
    if end_time == "unknown":
        return []
    windows: list[dict[str, Any]] = []
    for row in rows:
        start_time = format_clock(row.get("time_last_sale"))
        if start_time == "unknown":
            continue
        windows.append(
            {
                "category": str(row.get("category", "Stockout")).title(),
                "start_time": start_time,
                "end_time": end_time,
            }
        )
    return windows


def _intraday_sellout_rows(
    rows: list[dict[str, Any]],
    close_time: Any,
) -> list[dict[str, Any]]:
    """Return display rows for category sellouts against the service window."""

    close_minutes = minutes_from_clock(close_time)
    display_rows: list[dict[str, Any]] = []
    for row in rows:
        sale_time = row.get("time_last_sale")
        sale_minutes = minutes_from_clock(sale_time)
        minutes_before_close = (
            None if close_minutes is None or sale_minutes is None else close_minutes - sale_minutes
        )
        display_rows.append(
            {
                "category": str(row["category"]).title(),
                "sold": int(row["sold"]),
                "prepared": int(row["prepared"]),
                "last sale": format_clock(sale_time),
                "before close": format_minutes_before_close(minutes_before_close),
            }
        )
    return display_rows
