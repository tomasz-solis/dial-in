"""Close out tab: end-of-day entry that generates the next recommendation."""

from __future__ import annotations

from datetime import date, time, timedelta
from typing import Any

import pandas as pd
import streamlit as st

from dialin import ui_components as ui
from dialin.formatting import (
    format_service_window,
    minutes_from_clock,
    time_from_timestamp,
)
from dialin.repository import (
    OVERRIDE_REASON_OPTIONS,
    generate_and_store_recommendations,
    mark_closed_day,
    mark_missing_input,
    upsert_closeout,
)
from dialin.streamlit_cache import (
    clear_cached_reads,
    fetch_closeout_payload,
    fetch_next_open_business_date,
)


def render(
    database_url: str,
    account_id: str,
    username: str,
    location: dict[str, Any],
    business_date: date,
) -> None:
    """Render the manual v1 end-of-day entry form."""

    location_id = str(location["location_id"])
    payload = fetch_closeout_payload(database_url, account_id, location_id, business_date)
    frames = payload["frames"]
    defaults = _entry_defaults(frames, business_date)
    recommendation_rows = payload["recommendations"]
    recommendations_by_category = {
        str(row["category"]): row for row in recommendation_rows if row.get("category") is not None
    }
    flow = payload["flow"]
    default_stockout_time = _default_stockout_time(flow["hours"].get("close_time"))

    latest_generated = payload["latest_date"]
    next_open = fetch_next_open_business_date(
        database_url, account_id, location_id, business_date
    )
    target_date = next_open or business_date + timedelta(days=1)
    if latest_generated is not None and business_date <= latest_generated:
        closeout_mode = "Replay"
    else:
        closeout_mode = "Live test"
    st.markdown(ui.section_heading("Daily closeout", "End of day"), unsafe_allow_html=True)
    st.markdown(
        ui.closeout_status(
            business_date=business_date,
            target_date=target_date,
            mode=closeout_mode,
            service_window=format_service_window(flow["hours"]),
        ),
        unsafe_allow_html=True,
    )
    closed_day = st.checkbox(
        "Closed day",
        value=not defaults["is_open"],
        key=f"closed_day_{business_date.isoformat()}",
    )
    if closed_day:
        st.info("Closed days ignore sales, prep, and sellout fields.")

    with st.form("closeout"):
        st.markdown(
            ui.form_section("Service totals", "Observed sales and prepared quantities."),
            unsafe_allow_html=True,
        )
        menu_version = st.text_input("Menu version", value=defaults["menu_version"])
        drinks_col, sweet_col, savory_col = st.columns(3)
        drinks_sold = drinks_col.number_input(
            "Drinks sold",
            min_value=0,
            value=defaults["drinks_sold"],
            step=1,
            disabled=closed_day,
        )
        sweet_sold = sweet_col.number_input(
            "Sweet sold",
            min_value=0,
            value=defaults["sweet_sold"],
            step=1,
            disabled=closed_day,
        )
        sweet_prepared = sweet_col.number_input(
            "Sweet prepared",
            min_value=0,
            value=max(defaults["sweet_prepared"], defaults["sweet_sold"]),
            step=1,
            disabled=closed_day,
        )
        savory_sold = savory_col.number_input(
            "Savory sold",
            min_value=0,
            value=defaults["savory_sold"],
            step=1,
            disabled=closed_day,
        )
        savory_prepared = savory_col.number_input(
            "Savory prepared",
            min_value=0,
            value=max(defaults["savory_prepared"], defaults["savory_sold"]),
            step=1,
            disabled=closed_day,
        )
        st.markdown(
            ui.form_section("Sellout evidence", "Known last-sale evidence by category."),
            unsafe_allow_html=True,
        )
        stockout_col_1, stockout_col_2 = st.columns(2)
        with stockout_col_1:
            sweet_sold_out, sweet_time_last_sale = _render_stockout_inputs(
                "sweet",
                business_date,
                defaults,
                default_stockout_time,
                disabled=closed_day,
            )
        with stockout_col_2:
            savory_sold_out, savory_time_last_sale = _render_stockout_inputs(
                "savory",
                business_date,
                defaults,
                default_stockout_time,
                disabled=closed_day,
            )
        impossible_counts = sweet_sold > sweet_prepared or savory_sold > savory_prepared
        repair_counts = False
        if impossible_counts and not closed_day:
            st.warning("Sold cannot exceed prepared. Raise prepared to sold before saving.")
            repair_counts = st.checkbox("Repair by setting prepared equal to sold")
        st.markdown(
            ui.form_section("Recommendation attribution", "Optional override context."),
            unsafe_allow_html=True,
        )
        sweet_override_reason = _render_override_reason_select(
            recommendations_by_category.get("sweet"),
            "sweet",
            business_date,
        )
        savory_override_reason = _render_override_reason_select(
            recommendations_by_category.get("savory"),
            "savory",
            business_date,
        )
        action_col, missing_col = st.columns([1.35, 1.0], gap="medium")
        submitted = action_col.form_submit_button(
            "Save closeout and generate prep",
            type="primary",
            use_container_width=True,
        )
        missing_submitted = missing_col.form_submit_button(
            "Mark missing",
            use_container_width=True,
        )

    if submitted or missing_submitted:
        try:
            if missing_submitted:
                mark_missing_input(
                    database_url=database_url,
                    account_id=account_id,
                    location_id=location_id,
                    business_date=business_date,
                    timezone_name=str(location["timezone"]),
                    menu_version=menu_version,
                    corrected_by=username,
                )
            elif closed_day:
                mark_closed_day(
                    database_url=database_url,
                    account_id=account_id,
                    location_id=location_id,
                    business_date=business_date,
                    timezone_name=str(location["timezone"]),
                    menu_version=menu_version,
                    corrected_by=username,
                )
            else:
                if repair_counts:
                    sweet_prepared = max(sweet_prepared, sweet_sold)
                    savory_prepared = max(savory_prepared, savory_sold)
                upsert_closeout(
                    database_url=database_url,
                    account_id=account_id,
                    location_id=location_id,
                    business_date=business_date,
                    timezone_name=str(location["timezone"]),
                    drinks_sold=int(drinks_sold),
                    sweet_sold=int(sweet_sold),
                    savory_sold=int(savory_sold),
                    sweet_prepared=int(sweet_prepared),
                    savory_prepared=int(savory_prepared),
                    sweet_sold_out=sweet_sold_out,
                    savory_sold_out=savory_sold_out,
                    sweet_time_last_sale=sweet_time_last_sale,
                    savory_time_last_sale=savory_time_last_sale,
                    sweet_override_reason=sweet_override_reason,
                    savory_override_reason=savory_override_reason,
                    menu_version=menu_version,
                    corrected_by=username,
                )
            results = generate_and_store_recommendations(
                database_url,
                account_id,
                location_id,
                target_date,
            )
        except ValueError as exc:
            st.error(str(exc))
            return
        clear_cached_reads()
        action = "Marked input missing and generated" if missing_submitted else "Generated"
        st.success(
            f"{action} {len(results)} recommendation rows for {target_date}."
        )
        st.rerun()


def _entry_defaults(frames: dict[str, pd.DataFrame], business_date: date) -> dict[str, Any]:
    """Return generated replay defaults for the entry form."""

    defaults: dict[str, Any] = {
        "drinks_sold": 0,
        "sweet_sold": 0,
        "sweet_prepared": 0,
        "sweet_sold_out": False,
        "sweet_time_last_sale": None,
        "savory_sold": 0,
        "savory_prepared": 0,
        "savory_sold_out": False,
        "savory_time_last_sale": None,
        "menu_version": "v1",
        "is_open": True,
    }
    daily = frames["daily_metrics"].copy()
    daily["date"] = pd.to_datetime(daily["date"]).dt.date
    daily_row = daily[daily["date"] == business_date]
    if not daily_row.empty and pd.notna(daily_row.iloc[0]["drinks_sold"]):
        defaults["drinks_sold"] = int(daily_row.iloc[0]["drinks_sold"])
        defaults["menu_version"] = str(daily_row.iloc[0].get("menu_version", "v1"))
        defaults["is_open"] = bool(daily_row.iloc[0].get("is_open", True))
    else:
        if not daily_row.empty:
            defaults["menu_version"] = str(daily_row.iloc[0].get("menu_version", "v1"))
            defaults["is_open"] = bool(daily_row.iloc[0].get("is_open", True))
        defaults["drinks_sold"] = _trailing_int_default(
            daily[daily["is_open"] == True],  # noqa: E712
            business_date,
            "drinks_sold",
        )

    category = frames["daily_category_metrics"].copy()
    category["date"] = pd.to_datetime(category["date"]).dt.date
    exact_rows = category[category["date"] == business_date]
    for _, row in exact_rows.iterrows():
        name = str(row["category"])
        defaults[f"{name}_sold"] = int(row["sold"])
        defaults[f"{name}_prepared"] = int(row["prepared"])
        defaults[f"{name}_sold_out"] = bool(row.get("sold_out", False))
        defaults[f"{name}_time_last_sale"] = time_from_timestamp(row.get("time_last_sale"))
    if exact_rows.empty:
        pos_sold = _pos_sales_defaults(frames, business_date)
        for name in ("sweet", "savory"):
            category_rows = category[category["category"] == name]
            defaults[f"{name}_sold"] = pos_sold.get(
                name,
                _trailing_int_default(category_rows, business_date, "sold"),
            )
            defaults[f"{name}_prepared"] = max(
                _trailing_int_default(category_rows, business_date, "prepared"),
                defaults[f"{name}_sold"],
            )
    return defaults


def _render_stockout_inputs(
    category: str,
    business_date: date,
    defaults: dict[str, Any],
    default_time: time,
    disabled: bool = False,
) -> tuple[bool, time | None]:
    """Render optional sold-out and last-sale controls for one category."""

    label = category.title()
    sold_out = st.checkbox(
        f"{label} sold out",
        value=bool(defaults.get(f"{category}_sold_out", False)),
        disabled=disabled,
        key=f"{category}_sold_out_{business_date.isoformat()}",
    )
    existing_time = defaults.get(f"{category}_time_last_sale")
    known_time = st.checkbox(
        f"{label} sellout time known",
        value=existing_time is not None,
        disabled=disabled,
        key=f"{category}_sellout_known_{business_date.isoformat()}",
    )
    sale_time = st.time_input(
        f"{label} last sale",
        value=existing_time or default_time,
        disabled=disabled,
        key=f"{category}_last_sale_{business_date.isoformat()}",
    )
    return sold_out, _resolved_stockout_time(sold_out, known_time, sale_time)


def _resolved_stockout_time(
    sold_out: bool,
    known_time: bool,
    sale_time: time,
) -> time | None:
    """Return the sellout time that should be saved from closeout inputs."""

    if sold_out and known_time:
        return sale_time
    return None


def _default_stockout_time(close_time: Any) -> time:
    """Return a useful default stockout time near the end of service."""

    close_minutes = minutes_from_clock(close_time)
    if close_minutes is None:
        return time(12, 30)
    default_minutes = max(close_minutes - 30, 0)
    hour, minute = divmod(default_minutes, 60)
    return time(hour, minute)


def _pos_sales_defaults(frames: dict[str, pd.DataFrame], business_date: date) -> dict[str, int]:
    """Return imported POS category sales for a date when closeout rows are missing."""

    sales = frames.get("pos_daily_sales", pd.DataFrame()).copy()
    if sales.empty:
        return {}
    sales["date"] = pd.to_datetime(sales["date"]).dt.date
    exact_sales = sales[sales["date"] == business_date]
    return {
        str(row["category"]): int(row["units_sold"])
        for _, row in exact_sales.iterrows()
        if str(row["category"]) in {"sweet", "savory"}
    }


def _render_override_reason_select(
    recommendation: dict[str, Any] | None,
    category: str,
    business_date: date,
) -> str | None:
    """Render an optional override reason when a prior recommendation exists."""

    if recommendation is None:
        return None
    recommended_prep = int(recommendation["recommended_prep"])
    st.caption(f"{category.title()} recommendation for this day was {recommended_prep}.")
    return str(
        st.selectbox(
            f"{category.title()} override reason",
            ("No reason", *OVERRIDE_REASON_OPTIONS),
            key=f"{category}_override_reason_{business_date.isoformat()}",
        )
    )


def _trailing_int_default(frame: pd.DataFrame, business_date: date, column: str) -> int:
    """Return a same-weekday trailing default for dates outside generated history."""

    if frame.empty:
        return 0
    rows = frame.copy()
    rows["date"] = pd.to_datetime(rows["date"]).dt.date
    rows = rows[rows["date"] < business_date]
    same_weekday = rows[rows["date"].map(lambda item: item.weekday()) == business_date.weekday()]
    source = same_weekday.tail(4) if same_weekday.shape[0] >= 2 else rows.tail(14)
    if source.empty:
        return 0
    return max(0, round(float(source[column].dropna().mean())))
