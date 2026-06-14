"""Setup tab: hours, events, economics, workflow reference, and POS import."""

from __future__ import annotations

import json
from datetime import date, time
from typing import Any

import pandas as pd
import streamlit as st

from dialin import ui_components as ui
from dialin.formatting import (
    format_lift,
    format_percent,
    format_timestamp,
    time_value,
    weekday_labels,
)
from dialin.pos_import import (
    CategoryMapping,
    PosColumnMapping,
    PosImportPreview,
    csv_columns,
    mapping_snapshot,
    parse_keyword_text,
    preview_pos_import,
)
from dialin.repository import (
    apply_pos_import,
    economics_service_quantile,
    insert_manual_event,
    upsert_category_economics,
    upsert_location_hours,
)
from dialin.streamlit_cache import (
    SetupPayload,
    clear_cached_reads,
    fetch_setup_payload,
)

DEFAULT_DRINK_KEYWORDS = (
    "coffee, espresso, americano, latte, cappuccino, cortado, tea, juice, drink"
)
DEFAULT_SWEET_KEYWORDS = "croissant, pastry, cake, muffin, cookie, brownie, sweet"
DEFAULT_SAVORY_KEYWORDS = "sandwich, toast, bocadillo, quiche, empanada, savory"


def render(
    database_url: str,
    account_id: str,
    username: str,
    location: dict[str, Any],
    target_date: date,
) -> None:
    """Render the Setup tab: hours, events, economics, workflow, and POS import."""

    location_id = str(location["location_id"])
    payload = fetch_setup_payload(database_url, account_id, location_id, target_date)
    _render_setup_tab(database_url, account_id, location, target_date, payload)
    _render_import_tab(database_url, account_id, username, location, payload["recent_imports"])


def _render_setup_tab(
    database_url: str,
    account_id: str,
    location: dict[str, Any],
    target_date: date,
    payload: SetupPayload,
) -> None:
    """Render location setup, context logging, and economics controls."""

    location_id = str(location["location_id"])
    st.subheader("Setup")
    st.caption(
        "Season is derived from the calendar. Weather comes from the loaded forecast rows. "
        "Events and opening hours are owner-controlled here."
    )
    _render_hours_setup(
        database_url,
        account_id,
        location_id,
        target_date,
        payload["hours"],
    )
    _render_event_setup(
        database_url,
        account_id,
        location_id,
        target_date,
        payload["events"],
    )
    _render_economics_setup(
        database_url,
        account_id,
        location_id,
        target_date,
        payload["economics"],
    )
    with st.expander("Daily workflow reference"):
        st.dataframe(pd.DataFrame(_workflow_rows()), hide_index=True, width="stretch")


def _render_hours_setup(
    database_url: str,
    account_id: str,
    location_id: str,
    target_date: date,
    rows: list[dict[str, Any]],
) -> None:
    """Render and save the effective weekly opening-hours plan."""

    rows_by_day = {int(row["day_of_week"]): row for row in rows}
    st.markdown("#### Opening hours")
    with st.form("opening_hours_setup"):
        effective_from = st.date_input("Effective from", value=target_date)
        updates: list[dict[str, Any]] = []
        header_cols = st.columns([1.15, 0.8, 1.0, 1.0], gap="large")
        header_cols[0].markdown('<div class="di-hours-header">Day</div>', unsafe_allow_html=True)
        header_cols[1].markdown('<div class="di-hours-header">Open</div>', unsafe_allow_html=True)
        header_cols[2].markdown('<div class="di-hours-header">Opens</div>', unsafe_allow_html=True)
        header_cols[3].markdown('<div class="di-hours-header">Closes</div>', unsafe_allow_html=True)
        for day_of_week, label in enumerate(weekday_labels()):
            row = rows_by_day.get(day_of_week, {})
            is_open = bool(row.get("is_open", False))
            default_open = time_value(row.get("open_time"), time(9, 0))
            default_close = time_value(row.get("close_time"), time(13, 0))
            day_col, open_col, start_col, end_col = st.columns(
                [1.15, 0.8, 1.0, 1.0],
                gap="large",
            )
            day_col.markdown(
                f'<div class="di-hours-day">{ui.text(label)}</div>',
                unsafe_allow_html=True,
            )
            selected_open = open_col.checkbox(
                f"{label} open",
                value=is_open,
                key=f"hours_open_{day_of_week}",
                label_visibility="collapsed",
            )
            selected_start = start_col.time_input(
                f"{label} opens",
                value=default_open,
                key=f"hours_start_{day_of_week}",
                label_visibility="collapsed",
            )
            selected_end = end_col.time_input(
                f"{label} closes",
                value=default_close,
                key=f"hours_end_{day_of_week}",
                label_visibility="collapsed",
            )
            updates.append(
                {
                    "day_of_week": day_of_week,
                    "is_open": selected_open,
                    "open_time": selected_start if selected_open else None,
                    "close_time": selected_end if selected_open else None,
                }
            )
        submitted = st.form_submit_button("Save opening hours")

    if submitted:
        try:
            for update in updates:
                upsert_location_hours(
                    database_url=database_url,
                    account_id=account_id,
                    location_id=location_id,
                    day_of_week=int(update["day_of_week"]),
                    is_open=bool(update["is_open"]),
                    open_time=update["open_time"],
                    close_time=update["close_time"],
                    effective_from=effective_from,
                )
        except ValueError as exc:
            st.error(str(exc))
            return
        clear_cached_reads()
        st.success("Opening hours saved.")
        st.rerun()


def _render_event_setup(
    database_url: str,
    account_id: str,
    location_id: str,
    target_date: date,
    events: list[dict[str, Any]],
) -> None:
    """Render manual local event logging for recommendation context."""

    st.markdown("#### Events")
    with st.form("manual_event_setup"):
        event_date = st.date_input("Event date", value=target_date)
        name_col, type_col = st.columns([1.4, 1.0])
        event_name = name_col.text_input("Event name")
        event_type = type_col.selectbox(
            "Event type",
            ("local", "holiday", "market", "school", "weather", "other"),
        )
        impact_col, confidence_col = st.columns([1.0, 1.0])
        impact_pct = impact_col.slider("Expected demand lift", 0, 80, 10, 5)
        confidence = confidence_col.selectbox("Confidence", ("Medium", "Low", "High"))
        submitted = st.form_submit_button("Log event")

    if submitted:
        try:
            insert_manual_event(
                database_url=database_url,
                account_id=account_id,
                location_id=location_id,
                business_date=event_date,
                event_name=event_name,
                event_type=event_type,
                impact_score=impact_pct / 100,
                confidence=confidence,
            )
        except ValueError as exc:
            st.error(str(exc))
            return
        clear_cached_reads()
        st.success("Event logged.")
        st.rerun()

    if events:
        st.dataframe(pd.DataFrame(_event_display_rows(events)), hide_index=True, width="stretch")
    else:
        st.markdown(
            ui.empty_state("No nearby events", "No events are logged in the planning window."),
            unsafe_allow_html=True,
        )


def _render_economics_setup(
    database_url: str,
    account_id: str,
    location_id: str,
    target_date: date,
    economics_rows: list[dict[str, Any]],
) -> None:
    """Render the category economics form that controls service quantiles."""

    if not economics_rows:
        st.warning("No category economics are available for this date.")
        return

    with st.expander("Economics setup"):
        st.caption("These values set the waste/run-out tradeoff copied into each recommendation.")
        updates: list[dict[str, Any]] = []
        valid = True
        with st.form("economics_setup"):
            for row in economics_rows:
                category = str(row["category"])
                st.markdown(f"**{category.title()}**")
                price_col, cogs_col, salvage_col = st.columns(3)
                retail_price = price_col.number_input(
                    f"{category.title()} retail price",
                    min_value=0.0,
                    value=float(row["retail_price"]),
                    step=0.10,
                    format="%.2f",
                )
                unit_cogs = cogs_col.number_input(
                    f"{category.title()} unit COGS",
                    min_value=0.01,
                    value=max(float(row["unit_cogs"]), 0.01),
                    step=0.10,
                    format="%.2f",
                )
                salvage_pct = salvage_col.number_input(
                    f"{category.title()} salvage %",
                    min_value=0.0,
                    max_value=95.0,
                    value=float(row["salvage_share_default"]) * 100,
                    step=5.0,
                    format="%.1f",
                )
                drink_col, balk_col, service_col = st.columns(3)
                attached_drink_margin = drink_col.number_input(
                    f"{category.title()} attached drink margin",
                    min_value=0.0,
                    value=float(row["attached_drink_margin"]),
                    step=0.10,
                    format="%.2f",
                )
                attach_and_balk_pct = balk_col.number_input(
                    f"{category.title()} attach-and-balk %",
                    min_value=0.0,
                    max_value=100.0,
                    value=float(row["attach_and_balk_rate"]) * 100,
                    step=5.0,
                    format="%.1f",
                )
                salvage_share = salvage_pct / 100
                attach_and_balk_rate = attach_and_balk_pct / 100
                try:
                    service_level = economics_service_quantile(
                        retail_price=retail_price,
                        unit_cogs=unit_cogs,
                        salvage_share_default=salvage_share,
                        attached_drink_margin=attached_drink_margin,
                        attach_and_balk_rate=attach_and_balk_rate,
                    )
                    service_col.metric("Service level", format_percent(service_level))
                except ValueError as exc:
                    valid = False
                    service_level = float(row["service_quantile"])
                    service_col.warning(str(exc))
                st.caption(f"Source: {str(row.get('values_source', 'default')).replace('_', ' ')}")
                updates.append(
                    {
                        "category": category,
                        "retail_price": retail_price,
                        "unit_cogs": unit_cogs,
                        "salvage_share_default": salvage_share,
                        "attached_drink_margin": attached_drink_margin,
                        "attach_and_balk_rate": attach_and_balk_rate,
                        "service_quantile": service_level,
                    }
                )
            submitted = st.form_submit_button("Save economics")

        if submitted:
            if not valid:
                st.error("Fix the economics values before saving.")
                return
            for update in updates:
                upsert_category_economics(
                    database_url=database_url,
                    account_id=account_id,
                    location_id=location_id,
                    category=str(update["category"]),
                    effective_from=target_date,
                    retail_price=float(update["retail_price"]),
                    unit_cogs=float(update["unit_cogs"]),
                    salvage_share_default=float(update["salvage_share_default"]),
                    attached_drink_margin=float(update["attached_drink_margin"]),
                    attach_and_balk_rate=float(update["attach_and_balk_rate"]),
                )
            clear_cached_reads()
            st.success("Economics saved for future recommendations.")
            st.rerun()


def _event_display_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Format event rows for the setup table."""

    return [
        {
            "date": row["date"],
            "event": row["event_name"],
            "type": row["event_type"],
            "expected lift": format_lift(1 + float(row["impact_score"])),
            "confidence": row["confidence"],
            "source": str(row["source"]).replace("_", " "),
        }
        for row in rows
    ]


def _workflow_rows() -> list[dict[str, str]]:
    """Return the compact daily workflow shown in the app."""

    return [
        {
            "moment": "Before service",
            "action": "Check Today",
            "input": "Recommendation, range, confidence, and the why",
        },
        {
            "moment": "End of day",
            "action": "Submit Close out",
            "input": "Drinks sold, sold units, prepared units",
        },
        {
            "moment": "Backfill",
            "action": "Use Setup, POS CSV import",
            "input": "Historical POS CSV sales before API integration",
        },
        {
            "moment": "Exception",
            "action": "Mark closed or missing",
            "input": "Only when the day should not train demand",
        },
        {
            "moment": "Change",
            "action": "Update Setup",
            "input": "Economics or menu version changes",
        },
        {
            "moment": "Review",
            "action": "Check How it's doing",
            "input": "Calibration, baselines, overrides, waste and sellout proxies",
        },
    ]


def _render_import_tab(
    database_url: str,
    account_id: str,
    username: str,
    location: dict[str, Any],
    recent_imports: list[dict[str, Any]],
) -> None:
    """Render CSV POS import preview and apply controls."""

    location_id = str(location["location_id"])
    st.subheader("POS CSV import")
    st.caption("Line-item CSV backfill. Prepared quantities still come from closeout.")
    uploaded = st.file_uploader("CSV file", type=["csv"])
    if uploaded is None:
        _render_recent_pos_imports(recent_imports)
        return

    try:
        csv_text = _decode_uploaded_csv(uploaded.getvalue())
    except UnicodeDecodeError:
        st.error("CSV must be UTF-8 encoded.")
        return

    columns = csv_columns(csv_text)
    if not columns:
        st.error("CSV has no header row.")
        return

    date_column = st.selectbox(
        "Date column",
        columns,
        index=columns.index(_guess_column(columns, ("date", "business date", "day"))),
    )
    item_column = st.selectbox(
        "Item column",
        columns,
        index=columns.index(_guess_column(columns, ("item", "product", "name"))),
    )
    timestamp_options = ["Not included", *columns]
    timestamp_column = st.selectbox(
        "Timestamp column",
        timestamp_options,
        index=_optional_column_index(timestamp_options, columns, ("timestamp", "time", "created")),
    )
    quantity_options = ["Default to 1", *columns]
    quantity_column = st.selectbox(
        "Quantity column",
        quantity_options,
        index=_optional_column_index(quantity_options, columns, ("qty", "quantity", "units")),
    )
    drink_keywords = st.text_input("Drink keywords", value=DEFAULT_DRINK_KEYWORDS)
    sweet_keywords = st.text_input("Sweet keywords", value=DEFAULT_SWEET_KEYWORDS)
    savory_keywords = st.text_input("Savory keywords", value=DEFAULT_SAVORY_KEYWORDS)

    column_mapping = PosColumnMapping(
        date_column=date_column,
        item_column=item_column,
        timestamp_column=None if timestamp_column == "Not included" else timestamp_column,
        quantity_column=None if quantity_column == "Default to 1" else quantity_column,
    )
    category_mapping = CategoryMapping(
        drinks_keywords=parse_keyword_text(drink_keywords),
        sweet_keywords=parse_keyword_text(sweet_keywords),
        savory_keywords=parse_keyword_text(savory_keywords),
    )
    try:
        preview = preview_pos_import(
            csv_text=csv_text,
            columns=column_mapping,
            categories=category_mapping,
            timezone_name=str(location["timezone"]),
        )
    except ValueError as exc:
        st.error(str(exc))
        return

    _render_import_preview(preview)
    if preview.can_apply:
        st.caption("Applying replaces imported POS rollups for the previewed date range.")
        if st.button("Apply import"):
            result = apply_pos_import(
                database_url=database_url,
                account_id=account_id,
                location_id=location_id,
                filename=str(uploaded.name),
                created_by=username,
                timezone_name=str(location["timezone"]),
                preview=preview,
                mapping=mapping_snapshot(column_mapping, category_mapping),
            )
            clear_cached_reads()
            st.success(
                f"Applied {result['rows_imported']} rows for "
                f"{result['date_start']} to {result['date_end']}."
            )
            st.rerun()
    else:
        st.warning("Import needs at least one mapped drinks row before it can be applied.")
    _render_recent_pos_imports(recent_imports)


def _render_import_preview(preview: PosImportPreview) -> None:
    """Render POS import preview metrics, rollups, and sample errors."""

    st.markdown("**Preview**")
    summary = _import_summary_rows(preview)[0]
    columns = st.columns(4, gap="medium")
    preview_cards = (
        ("Rows read", summary["rows read"], summary["date range"]),
        ("Rows imported", summary["rows imported"], "Mapped sales rows"),
        ("Rows rejected", summary["rows rejected"], "Validation failures"),
        ("Timestamp coverage", summary["timestamp coverage"], f"Can apply: {summary['can apply']}"),
    )
    for column, (label, value, caption) in zip(columns, preview_cards, strict=True):
        with column:
            st.markdown(ui.metric_card(label, value, caption), unsafe_allow_html=True)
    if preview.rollups:
        st.dataframe(pd.DataFrame(_import_rollup_rows(preview)), hide_index=True, width="stretch")
    if preview.errors:
        with st.expander("Rejected rows"):
            st.dataframe(
                pd.DataFrame(_import_error_rows(preview)),
                hide_index=True,
                width="stretch",
            )


def _render_recent_pos_imports(rows: list[dict[str, Any]]) -> None:
    """Render recent POS import runs."""

    with st.expander("Recent POS imports"):
        if not rows:
            st.markdown(
                ui.empty_state("No POS imports", "No POS imports have been applied yet."),
                unsafe_allow_html=True,
            )
            return
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


def _import_summary_rows(preview: PosImportPreview) -> list[dict[str, Any]]:
    """Return compact display rows for a POS import preview summary."""

    return [
        {
            "date range": _format_import_date_range(preview),
            "rows read": preview.rows_read,
            "rows imported": preview.rows_imported,
            "rows rejected": preview.rows_rejected,
            "timestamp coverage": format_percent(preview.timestamp_coverage),
            "can apply": "yes" if preview.can_apply else "no",
        }
    ]


def _import_rollup_rows(preview: PosImportPreview) -> list[dict[str, Any]]:
    """Return display rows for POS daily sales rollups."""

    return [
        {
            "date": rollup.business_date,
            "category": rollup.category,
            "units sold": rollup.units_sold,
            "first sale": format_timestamp(rollup.first_sale_at),
            "last sale": format_timestamp(rollup.last_sale_at),
        }
        for rollup in preview.rollups
    ]


def _import_error_rows(preview: PosImportPreview, limit: int = 12) -> list[dict[str, Any]]:
    """Return display rows for rejected POS CSV rows."""

    return [
        {
            "row": error.row_number,
            "reason": error.reason,
            "raw row": json.dumps(error.raw_row, sort_keys=True),
        }
        for error in preview.errors[:limit]
    ]


def _format_import_date_range(preview: PosImportPreview) -> str:
    """Format the date range of a POS import preview."""

    if preview.date_start is None or preview.date_end is None:
        return "none"
    if preview.date_start == preview.date_end:
        return str(preview.date_start)
    return f"{preview.date_start} to {preview.date_end}"


def _guess_column(columns: list[str], candidates: tuple[str, ...]) -> str:
    """Guess a CSV column from candidate text fragments."""

    for candidate in candidates:
        for column in columns:
            if candidate in column.casefold():
                return column
    return columns[0]


def _optional_column_index(
    options: list[str],
    columns: list[str],
    candidates: tuple[str, ...],
) -> int:
    """Return a selectbox index for an optional CSV column."""

    guessed = _guess_column(columns, candidates)
    if guessed == columns[0] and not any(
        candidate in guessed.casefold() for candidate in candidates
    ):
        return 0
    return options.index(guessed)


def _decode_uploaded_csv(content: bytes) -> str:
    """Decode uploaded CSV bytes using the expected UTF-8 encoding."""

    return content.decode("utf-8-sig")
