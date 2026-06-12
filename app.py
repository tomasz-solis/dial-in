"""Streamlit app for the Dial In synthetic café demo."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit_authenticator as stauth
from dotenv import load_dotenv

from dialin import charts
from dialin import ui_components as ui
from dialin.config import Settings, load_settings
from dialin.db import assert_not_owner_connection
from dialin.demo_freshness import ensure_demo_data_fresh
from dialin.metrics import calibration_coverage, evaluate_model_vs_baselines
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
    OVERRIDE_REASON_OPTIONS,
    apply_pos_import,
    economics_service_quantile,
    fetch_category_economics,
    fetch_data_corrections,
    fetch_events_for_window,
    fetch_history_frames,
    fetch_intraday_demo,
    fetch_location_hours_plan,
    fetch_recent_pos_import_runs,
    fetch_recommendation_context,
    fetch_recommendation_outcomes,
    fetch_recommendations_for_date,
    generate_and_store_recommendations,
    insert_manual_event,
    latest_business_date,
    list_locations,
    mark_closed_day,
    mark_missing_input,
    scorecard,
    upsert_category_economics,
    upsert_closeout,
    upsert_location_hours,
)

DEFAULT_DRINK_KEYWORDS = (
    "coffee, espresso, americano, latte, cappuccino, cortado, tea, juice, drink"
)
DEFAULT_SWEET_KEYWORDS = "croissant, pastry, cake, muffin, cookie, brownie, sweet"
DEFAULT_SAVORY_KEYWORDS = "sandwich, toast, bocadillo, quiche, empanada, savory"
PLOTLY_CONFIG: dict[str, bool] = {"displayModeBar": False, "responsive": True}


def main() -> None:
    """Render the login-gated Dial In demo."""

    st.set_page_config(page_title="Dial In", page_icon="D", layout="wide")
    _style()

    auth_context = _authenticate()
    if auth_context is None:
        return

    settings = _load_runtime_settings()
    try:
        assert_not_owner_connection(settings.database_url, settings.app_database_role)
    except Exception as exc:
        st.error(str(exc))
        st.stop()

    account_id = auth_context["account_id"]
    locations = list_locations(settings.database_url, account_id)
    if not locations:
        st.error("No locations are available for this account.")
        st.stop()

    location = locations[0]
    today = _today_for_location(str(location["timezone"]))
    _ensure_demo_freshness_once(
        database_url=settings.database_url,
        account_id=account_id,
        location_id=str(location["location_id"]),
        today=today,
    )

    latest_date = latest_business_date(settings.database_url, account_id, location["location_id"])
    if latest_date is None:
        st.error("No synthetic history has been loaded yet.")
        st.stop()

    _init_cursor(latest_date, today)
    closeout_date = st.session_state["replay_date"]
    target_date = closeout_date + timedelta(days=1)
    _render_app_header(location, closeout_date, target_date)

    command_tab, closeout_tab, accuracy_tab, flow_tab, setup_tab, import_tab = st.tabs(
        [
            "Command Center",
            "Daily Closeout",
            "Accuracy",
            "Service Flow",
            "Setup",
            "POS Import",
        ]
    )
    with command_tab:
        _render_command_center(
            settings.database_url,
            account_id,
            location,
            closeout_date,
            target_date,
        )
    with closeout_tab:
        _render_entry(
            settings.database_url,
            account_id,
            auth_context["username"],
            location,
            closeout_date,
        )
    with accuracy_tab:
        _render_accuracy_tab(settings.database_url, account_id, location["location_id"])
        _render_correction_audit(settings.database_url, account_id, location["location_id"])
    with flow_tab:
        _render_service_flow_tab(
            settings.database_url,
            account_id,
            location["location_id"],
            closeout_date,
            target_date,
        )
    with setup_tab:
        _render_setup_tab(
            settings.database_url,
            account_id,
            location,
            target_date,
        )
    with import_tab:
        _render_import_tab(
            settings.database_url,
            account_id,
            auth_context["username"],
            location,
        )
    _render_replay_controls(latest_date, today)


def _ensure_demo_freshness_once(
    database_url: str,
    account_id: str,
    location_id: str,
    today: date,
) -> None:
    """Run demo data freshness once per tenant/location/day in a Streamlit session."""

    session_key = f"demo_freshness:{account_id}:{location_id}:{today.isoformat()}"
    if st.session_state.get(session_key) is True:
        return
    try:
        ensure_demo_data_fresh(
            database_url=database_url,
            account_id=account_id,
            location_id=location_id,
            today=today,
        )
    except Exception as exc:
        st.warning(f"Demo data refresh failed, so the app is using loaded data only: {exc}")
        return
    st.session_state[session_key] = True


def _authenticate() -> dict[str, str] | None:
    """Authenticate through streamlit-authenticator and return username/account context."""

    auth = st.secrets.get("auth")
    if auth is None:
        st.warning("Configure `.streamlit/secrets.toml` from `.streamlit/secrets.example.toml`.")
        return None

    credentials = _plain_mapping(auth["credentials"])
    cookie_name = str(auth["cookie_name"])
    cookie_key = str(auth["cookie_key"])
    cookie_expiry_days = int(auth.get("cookie_expiry_days", 7))
    authenticator = stauth.Authenticate(
        credentials,
        cookie_name,
        cookie_key,
        cookie_expiry_days,
        auto_hash=False,
    )

    login_result = authenticator.login(location="main", key="Login")
    if login_result is None:
        name = st.session_state.get("name")
        authentication_status = st.session_state.get("authentication_status")
        username = st.session_state.get("username")
    else:
        name, authentication_status, username = login_result

    if authentication_status is False:
        st.error("Email or password is incorrect.")
        return None
    if authentication_status is None:
        st.info("Log in to view the synthetic café demo.")
        return None
    if username is None:
        st.error("Login succeeded but no username was returned.")
        return None

    authenticator.logout("Logout", "sidebar")
    st.sidebar.markdown(ui.sidebar_user(name or username), unsafe_allow_html=True)
    user_config = credentials["usernames"][username]
    return {"username": str(username), "account_id": str(user_config["account_id"])}


def _plain_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    """Recursively copy Streamlit secrets into mutable plain dictionaries."""

    copied: dict[str, Any] = {}
    for key, item in value.items():
        if isinstance(item, Mapping):
            copied[str(key)] = _plain_mapping(item)
        else:
            copied[str(key)] = item
    return copied


def _runtime_env_file() -> Path:
    """Return the safest local env file for the Streamlit runtime."""

    local_env = Path(".env.local")
    if local_env.exists():
        return local_env
    return Path(".env")


def _load_runtime_settings() -> Settings:
    """Load Streamlit settings with local app-role values taking precedence."""

    env_file = _runtime_env_file()
    if env_file.exists():
        load_dotenv(env_file, override=True)
    return load_settings(env_file)


def _init_cursor(latest_date: date, today: date) -> None:
    """Initialize the closeout cursor to today when possible, otherwise replay history."""

    if "replay_date" not in st.session_state:
        st.session_state["replay_date"] = today if today >= latest_date else latest_date


def _render_app_header(
    location: dict[str, Any],
    closeout_date: date,
    target_date: date,
) -> None:
    """Render the branded page header with the active operating dates."""

    st.markdown(
        _app_header_html(
            brand="Dial In",
            location_name=location["name"],
            location_area=_location_area(location),
            closeout_date=closeout_date,
            target_date=target_date,
        ),
        unsafe_allow_html=True,
    )


def _app_header_html(
    brand: Any,
    location_name: Any,
    location_area: Any,
    closeout_date: Any,
    target_date: Any,
) -> str:
    """Return header HTML, tolerating stale Streamlit-imported UI modules."""

    renderer = getattr(ui, "app_header", None)
    if callable(renderer):
        return str(
            renderer(
                brand=brand,
                location_name=location_name,
                location_area=location_area,
                closeout_date=closeout_date,
                target_date=target_date,
            )
        )
    return (
        '<div class="di-topbar">'
        "<div>"
        f'<div class="di-brand">{ui.text(brand)}</div>'
        f'<div class="di-location">{ui.text(location_name)} · {ui.text(location_area)}</div>'
        "</div>"
        '<div class="di-date-stack" aria-label="Active planning dates">'
        '<div class="di-date-row">'
        "<span>Closeout</span>"
        f"<strong>{ui.text(closeout_date)}</strong>"
        "</div>"
        '<div class="di-date-row di-date-row-primary">'
        "<span>Prep</span>"
        f"<strong>{ui.text(target_date)}</strong>"
        "</div>"
        "</div>"
        "</div>"
    )


def _location_area(location: Mapping[str, Any]) -> str:
    """Return the human location area shown in the header."""

    if str(location.get("location_id")) == "loc_fadri_main":
        return "Cambrils, Tarragona"
    city = str(location.get("city") or "").strip()
    country = str(location.get("country") or "").strip()
    if city:
        return city
    return country or "Unknown location"


def _render_command_center(
    database_url: str,
    account_id: str,
    location: dict[str, Any],
    closeout_date: date,
    target_date: date,
) -> None:
    """Render the main daily decision view for the operator."""

    location_id = str(location["location_id"])
    recommendation_rows = fetch_recommendations_for_date(
        database_url,
        account_id,
        location_id,
        target_date,
    )
    context = fetch_recommendation_context(database_url, account_id, location_id, target_date)
    flow = fetch_intraday_demo(database_url, account_id, location_id, target_date)

    if not recommendation_rows:
        st.info(
            f"No prep recommendation is stored for {target_date}. "
            f"Close out {closeout_date} to generate the next decision."
        )
        return

    _render_recommendation_hero(recommendation_rows, context, flow, target_date)
    _render_prep_cards(recommendation_rows)

    st.markdown("#### Demand flow")
    _render_demand_flow(
        curve=flow["curve"],
        sellouts=flow["sellouts"],
        close_time=flow["hours"].get("close_time"),
        title="Expected drinks by half-hour",
        key=f"command_pressure_{target_date.isoformat()}",
    )
    st.markdown("#### Context inputs")
    _render_context_cards(context, target_date)


def _render_recommendation_hero(
    rows: list[dict[str, Any]],
    context: dict[str, Any],
    flow: dict[str, Any],
    target_date: date,
) -> None:
    """Render the prominent prep recommendation header."""

    prep_summary = f"Prep for {target_date.strftime('%A')}"
    confidence = _confidence_summary(rows)
    risk = _risk_summary(rows)
    weather = _weather_summary(context.get("weather"))
    event = _event_summary(context.get("events", []))
    service_window = _format_service_window(flow["hours"])
    subtitle_parts = [target_date.strftime("%A, %b %-d"), service_window]
    if weather != "Seasonal normal":
        subtitle_parts.append(weather)
    if event != "No event logged":
        subtitle_parts.append(event)
    st.markdown(
        ui.command_hero(
            prep_summary=prep_summary,
            subtitle=" · ".join(subtitle_parts),
            prep_tiles_html=_hero_prep_tiles(rows),
            badges_html=ui.badges((confidence, risk), tone="dark"),
            driver_html=_command_driver_chips(rows, context, target_date),
            image_uri=_cafe_image_uri(),
        ),
        unsafe_allow_html=True,
    )


def _render_prep_cards(rows: list[dict[str, Any]]) -> None:
    """Render category prep cards under the hero decision."""

    columns = st.columns(len(rows), gap="medium")
    for column, row in zip(columns, rows, strict=False):
        with column:
            drivers = _driver_chips(row.get("top_drivers", []))
            st.markdown(
                ui.prep_card(
                    category=str(row["category"]).title(),
                    recommended=int(row["recommended_prep"]),
                    demand_range=(
                        f"{int(row['demand_p_lower'])}-{int(row['demand_p_upper'])}"
                        f" · p50 {int(row['demand_p50'])}"
                    ),
                    confidence=row["confidence"],
                    service_level=_format_percent(float(row["service_quantile"])),
                    driver_html=drivers,
                ),
                unsafe_allow_html=True,
            )


def _render_context_cards(context: dict[str, Any], target_date: date) -> None:
    """Render the weather, event, and season inputs as compact cards."""

    weather = context.get("weather")
    events = context.get("events", [])
    cards = [
        ("Weather", _weather_summary(weather), _weather_detail(weather)),
        ("Events", _event_summary(events), _event_detail(events)),
        ("Season", _season_label(target_date), target_date.strftime("%A, %B %-d")),
    ]
    st.markdown(
        ui.card_grid(
            (ui.context_card(title, value, caption) for title, value, caption in cards),
            columns=3,
        ),
        unsafe_allow_html=True,
    )


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


def _render_model_quality(database_url: str, account_id: str, location_id: str) -> None:
    """Render calibration coverage and naive-baseline verdicts (PRD section 6.1)."""

    outcomes = fetch_recommendation_outcomes(database_url, account_id, location_id)
    matched = pd.DataFrame(outcomes)
    if matched.empty:
        return
    history = fetch_history_frames(database_url, account_id, location_id)[
        "daily_category_metrics"
    ]
    if "input_source" in history.columns:
        history = history[history["input_source"] != "imputed"]
    calibration = calibration_coverage(matched)
    evaluation = evaluate_model_vs_baselines(matched, history)

    st.markdown("#### Is the model earning trust?")
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
        "Scored on uncensored days only: sold-out days hide true demand, so they can "
        "neither confirm nor refute a forecast. Pinball loss is evaluated at each "
        "recommendation's own service quantile."
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


def _coverage_label(calibration: dict[str, Any]) -> str:
    """Return the headline calibration coverage value."""

    coverage = calibration.get("coverage")
    if coverage is None:
        return "Not enough data"
    return _format_percent(float(coverage))


def _coverage_caption(calibration: dict[str, Any]) -> str:
    """Return the calibration caption with the censoring exclusion made visible."""

    uncensored = int(calibration.get("uncensored_rows", 0))
    censored_share = float(calibration.get("censored_share", 0.0))
    return (
        f"Target ~80% · {uncensored} uncensored days · "
        f"{_format_percent(censored_share)} of days sold out and are excluded."
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
    return f"Pinball loss {model:.2f} vs {baseline:.2f} · {evaluation['evaluated_rows']} days."


def _render_accuracy_tab(database_url: str, account_id: str, location_id: str) -> None:
    """Render observed accuracy and business impact proxy charts."""

    card = scorecard(database_url, account_id, location_id)
    frame = _accuracy_frame(card["rows"])
    st.subheader("Accuracy and business impact")
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


def _render_service_flow_tab(
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
        service_window=_format_service_window(hours),
        expected_drinks=int(flow["expected_drinks"]),
        traffic_source=_format_source_label(flow["expected_source"]),
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


def _render_setup_tab(
    database_url: str,
    account_id: str,
    location: dict[str, Any],
    target_date: date,
) -> None:
    """Render location setup, context logging, and economics controls."""

    location_id = str(location["location_id"])
    st.subheader("Setup")
    st.caption(
        "Season is derived from the calendar. Weather comes from the loaded forecast rows. "
        "Events and opening hours are owner-controlled here."
    )
    _render_hours_setup(database_url, account_id, location_id, target_date)
    _render_event_setup(database_url, account_id, location_id, target_date)
    _render_economics_setup(database_url, account_id, location_id, target_date)
    with st.expander("Daily workflow reference"):
        st.dataframe(pd.DataFrame(_workflow_rows()), hide_index=True, width="stretch")


def _render_hours_setup(
    database_url: str,
    account_id: str,
    location_id: str,
    target_date: date,
) -> None:
    """Render and save the effective weekly opening-hours plan."""

    rows = fetch_location_hours_plan(database_url, account_id, location_id, target_date)
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
        for day_of_week, label in enumerate(_weekday_labels()):
            row = rows_by_day.get(day_of_week, {})
            is_open = bool(row.get("is_open", False))
            default_open = _time_value(row.get("open_time"), time(9, 0))
            default_close = _time_value(row.get("close_time"), time(13, 0))
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
        st.success("Opening hours saved.")
        st.rerun()


def _render_event_setup(
    database_url: str,
    account_id: str,
    location_id: str,
    target_date: date,
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
        st.success("Event logged.")
        st.rerun()

    events = fetch_events_for_window(
        database_url,
        account_id,
        location_id,
        target_date - timedelta(days=14),
        target_date + timedelta(days=45),
    )
    if events:
        st.dataframe(pd.DataFrame(_event_display_rows(events)), hide_index=True, width="stretch")
    else:
        st.markdown(
            ui.empty_state("No nearby events", "No events are logged in the planning window."),
            unsafe_allow_html=True,
        )


def _prep_summary(rows: list[dict[str, Any]]) -> str:
    """Return a compact prep summary for the command-center hero."""

    return " · ".join(
        f"{int(row['recommended_prep'])} {str(row['category']).title()}" for row in rows
    )


def _hero_prep_tiles(rows: list[dict[str, Any]]) -> str:
    """Return readable prep tiles for the Command Center hero."""

    return "".join(
        ui.hero_prep_tile(
            category=str(row["category"]).title(),
            recommended=int(row["recommended_prep"]),
            demand_range=f"{int(row['demand_p_lower'])}-{int(row['demand_p_upper'])}",
            confidence=row["confidence"],
        )
        for row in rows
    )


def _confidence_summary(rows: list[dict[str, Any]]) -> str:
    """Return a single confidence label for a recommendation set."""

    confidences = {str(row.get("confidence", "Low")) for row in rows}
    if len(confidences) == 1:
        return f"{confidences.pop()} confidence"
    if "Low" in confidences:
        return "Mixed confidence"
    return "Medium confidence"


def _risk_summary(rows: list[dict[str, Any]]) -> str:
    """Return a compact risk label from category risk flags."""

    risks = [str(row.get("risk_flag", "balanced")) for row in rows]
    if any("stockout" in risk.casefold() or "short" in risk.casefold() for risk in risks):
        return "Run-out risk visible"
    if any("waste" in risk.casefold() for risk in risks):
        return "Waste risk visible"
    return "Balanced risk"


def _weather_summary(weather: dict[str, Any] | None) -> str:
    """Return a short weather label for the recommendation context."""

    if not weather:
        return "Seasonal normal"
    condition = str(weather.get("condition", "unknown")).title()
    temp = float(weather.get("temp_forecast", 0.0))
    return f"{condition}, {temp:.0f}C"


def _format_source_label(value: Any) -> str:
    """Format source labels without title-case hyphen artifacts."""

    return str(value).replace("-", " ").replace("_", " ").strip().capitalize()


def _weather_detail(weather: dict[str, Any] | None) -> str:
    """Return compact weather detail text for context cards."""

    if not weather:
        return "No forecast row; lower confidence."
    rain = float(weather.get("rain_forecast", 0.0))
    return f"Rain {rain:.1f} mm · made {_format_timestamp(weather.get('forecast_made_at'))}"


def _event_summary(events: Any) -> str:
    """Return a short event label for the recommendation context."""

    if not events:
        return "No event logged"
    first = events[0]
    return str(first.get("event_name", "Local event"))


def _event_detail(events: Any) -> str:
    """Return compact event detail text for context cards."""

    if not events:
        return "No event lift applied."
    first = events[0]
    impact = float(first.get("impact_score", 0.0))
    return (
        f"{str(first.get('event_type', 'event')).title()} · {_format_lift(1 + impact)} · "
        f"{first.get('confidence', 'Unknown')} confidence"
    )


def _driver_chips(value: Any) -> str:
    """Return HTML chips for the top recommendation drivers."""

    drivers = value
    if isinstance(drivers, str):
        drivers = json.loads(drivers)
    if not drivers:
        return ui.chip("baseline")
    chips = []
    for driver in drivers[:3]:
        label = _format_driver(driver)
        chips.append(ui.chip(label))
    return "".join(chips)


def _command_driver_chips(
    rows: list[dict[str, Any]],
    context: dict[str, Any],
    target_date: date,
) -> str:
    """Return hero driver chips from context and recommendation drivers."""

    labels = [_season_label(target_date)]
    weather = _weather_summary(context.get("weather"))
    event = _event_summary(context.get("events", []))
    if weather != "Seasonal normal":
        labels.append(weather)
    if event != "No event logged":
        labels.append(event)
    for row in rows:
        drivers = row.get("top_drivers", [])
        if isinstance(drivers, str):
            drivers = json.loads(drivers)
        for driver in drivers[:2]:
            label = _format_driver(driver)
            if label not in labels:
                labels.append(label)
    return "".join(ui.chip(label) for label in labels[:5])


@st.cache_data(show_spinner=False)
def _cafe_image_uri() -> str:
    """Return the local cafe image URI used by the Command Center hero."""

    return ui.image_data_uri()


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
    followed_rate = "No attribution" if attributed == 0 else _format_percent(adhered / attributed)
    return {
        "rows": str(len(card.get("rows", []))),
        "waste_delta_label": waste_delta_label,
        "followed_rate": followed_rate,
    }


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


def _sellout_timing_frame(rows: list[dict[str, Any]], close_time: Any) -> pd.DataFrame:
    """Return chart rows for known sellout timing relative to close."""

    close_minutes = _minutes_from_clock(close_time)
    if close_minutes is None:
        return pd.DataFrame()

    records: list[dict[str, Any]] = []
    for row in rows:
        sale_minutes = _minutes_from_clock(row.get("time_last_sale"))
        if sale_minutes is None:
            continue
        minutes_before_close = close_minutes - sale_minutes
        records.append(
            {
                "category": str(row["category"]).title(),
                "minutes_before_close": minutes_before_close,
                "last_sale": _format_clock(row.get("time_last_sale")),
                "severity_color": _sellout_severity_color(minutes_before_close),
            }
        )
    return pd.DataFrame.from_records(records)


def _stockout_windows(rows: list[dict[str, Any]], close_time: Any) -> list[dict[str, Any]]:
    """Return known stockout windows for pressure-chart overlays."""

    end_time = _format_clock(close_time)
    if end_time == "unknown":
        return []
    windows: list[dict[str, Any]] = []
    for row in rows:
        start_time = _format_clock(row.get("time_last_sale"))
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


def _sellout_severity_color(minutes_before_close: int) -> str:
    """Return a chart color for sellout timing severity."""

    if minutes_before_close >= 90:
        return charts.RED
    if minutes_before_close >= 30:
        return charts.MUTED
    return charts.GREEN


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
    display["followed"] = display["adhered"].map(_format_adherence)
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


def _format_adherence(value: Any) -> str:
    """Format recommendation attribution for charts and tables."""

    if value is True:
        return "Followed"
    if value is False:
        return "Overridden"
    return "Unattributed"


def _weekday_labels() -> tuple[str, ...]:
    """Return weekday labels in Postgres weekday order."""

    return ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def _time_value(value: Any, fallback: time) -> time:
    """Return a time value from database output or a fallback."""

    if isinstance(value, time):
        return value
    if value is None or pd.isna(value):
        return fallback
    timestamp = pd.Timestamp(value)
    return time(int(timestamp.hour), int(timestamp.minute))


def _event_display_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Format event rows for the setup table."""

    return [
        {
            "date": row["date"],
            "event": row["event_name"],
            "type": row["event_type"],
            "expected lift": _format_lift(1 + float(row["impact_score"])),
            "confidence": row["confidence"],
            "source": str(row["source"]).replace("_", " "),
        }
        for row in rows
    ]


def _render_recommendation(
    database_url: str,
    account_id: str,
    location_id: str,
    target_date: date,
) -> None:
    """Render the persisted recommendation set for the selected closeout date."""

    rows = fetch_recommendations_for_date(database_url, account_id, location_id, target_date)
    st.subheader("Next prep recommendation")
    if not rows:
        st.info(
            f"No recommendation has been generated for {target_date} yet. "
            "Submit the end-of-day numbers below."
        )
        return

    st.write(f"Target date: **{target_date}**")
    columns = st.columns(len(rows))
    for column, row in zip(columns, rows, strict=False):
        with column:
            st.metric(str(row["category"]).title(), int(row["recommended_prep"]))
            st.caption(
                f"Demand range {row['demand_p_lower']}-{row['demand_p_upper']} · "
                f"{row['confidence']} confidence"
            )
            st.write(str(row["risk_flag"]))

    context = fetch_recommendation_context(database_url, account_id, location_id, target_date)
    _render_context_panels(context, target_date)

    with st.expander("Why"):
        for row in rows:
            st.write(f"**{str(row['category']).title()}**")
            drivers = row["top_drivers"]
            if isinstance(drivers, str):
                drivers = json.loads(drivers)
            for driver in drivers:
                st.write(_format_driver(driver))


def _render_intraday_demo(
    database_url: str,
    account_id: str,
    location_id: str,
    business_date: date,
) -> None:
    """Render the demo service-hours and daypart pressure panel."""

    demo = fetch_intraday_demo(database_url, account_id, location_id, business_date)
    hours = demo["hours"]
    st.subheader("Service pressure")
    st.caption("Synthetic daypart shape from daily history; not live POS intraday data.")
    service_col, drinks_col = st.columns(2)
    service_col.metric("Service window", _format_service_window(hours))
    drinks_col.metric("Expected drinks", int(demo["expected_drinks"]))
    st.caption(f"Traffic source: {demo['expected_source']}. Hours source: {hours['source']}.")

    if not hours["is_open"]:
        st.info("This date is marked closed in the current hours plan.")
        return

    curve = demo["curve"]
    if curve:
        curve_frame = pd.DataFrame(curve).set_index("time")
        st.line_chart(curve_frame[["expected_drinks"]])

    sellout_rows = _intraday_sellout_rows(demo["sellouts"], hours.get("close_time"))
    if sellout_rows:
        st.dataframe(pd.DataFrame(sellout_rows), hide_index=True, width="stretch")
    else:
        st.caption("No category sellout time recorded for this date.")


def _render_entry(
    database_url: str,
    account_id: str,
    username: str,
    location: dict[str, Any],
    business_date: date,
) -> None:
    """Render the manual v1 end-of-day entry form."""

    location_id = str(location["location_id"])
    frames = fetch_history_frames(database_url, account_id, location_id)
    defaults = _entry_defaults(frames, business_date)
    recommendation_rows = fetch_recommendations_for_date(
        database_url,
        account_id,
        location_id,
        business_date,
    )
    recommendations_by_category = {
        str(row["category"]): row for row in recommendation_rows if row.get("category") is not None
    }
    flow = fetch_intraday_demo(database_url, account_id, location_id, business_date)
    default_stockout_time = _default_stockout_time(flow["hours"].get("close_time"))

    latest_generated = latest_business_date(database_url, account_id, location_id)
    target_date = business_date + timedelta(days=1)
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
            service_window=_format_service_window(flow["hours"]),
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
        action = "Marked input missing and generated" if missing_submitted else "Generated"
        st.success(
            f"{action} {len(results)} recommendation rows for {target_date}."
        )
        st.rerun()


def _render_import_tab(
    database_url: str,
    account_id: str,
    username: str,
    location: dict[str, Any],
) -> None:
    """Render CSV POS import preview and apply controls."""

    location_id = str(location["location_id"])
    st.subheader("POS CSV import")
    st.caption("Line-item CSV backfill. Prepared quantities still come from closeout.")
    uploaded = st.file_uploader("CSV file", type=["csv"])
    if uploaded is None:
        _render_recent_pos_imports(database_url, account_id, location_id)
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
            st.success(
                f"Applied {result['rows_imported']} rows for "
                f"{result['date_start']} to {result['date_end']}."
            )
            st.rerun()
    else:
        st.warning("Import needs at least one mapped drinks row before it can be applied.")
    _render_recent_pos_imports(database_url, account_id, location_id)


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


def _render_recent_pos_imports(database_url: str, account_id: str, location_id: str) -> None:
    """Render recent POS import runs."""

    rows = fetch_recent_pos_import_runs(database_url, account_id, location_id)
    with st.expander("Recent POS imports"):
        if not rows:
            st.markdown(
                ui.empty_state("No POS imports", "No POS imports have been applied yet."),
                unsafe_allow_html=True,
            )
            return
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


def _render_workflow_tab(closeout_date: date, target_date: date) -> None:
    """Render a compact operator workflow reference."""

    st.subheader("Workflow")
    st.caption(f"Close out {closeout_date}; review prep for {target_date}.")
    st.dataframe(pd.DataFrame(_workflow_rows()), hide_index=True, width="stretch")
    st.info(
        "Most days only need the closeout counts. Use Setup when economics or "
        "menu version changes, and use Performance when reviewing whether prior "
        "recommendations were followed."
    )


def _render_economics_setup(
    database_url: str,
    account_id: str,
    location_id: str,
    target_date: date,
) -> None:
    """Render the category economics form that controls service quantiles."""

    economics_rows = fetch_category_economics(database_url, account_id, location_id, target_date)
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
                    service_col.metric("Service level", _format_percent(service_level))
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
            st.success("Economics saved for future recommendations.")
            st.rerun()


def _render_scorecard(database_url: str, account_id: str, location_id: str) -> None:
    """Render the observed-only replay comparison."""

    card = scorecard(database_url, account_id, location_id)
    st.subheader("How Dial In compares")
    st.caption(
        "Synthetic replay vs a simulated conservative gut-prepping baseline. "
        "This is not a real counterfactual or validated operator impact."
    )
    col1, col2 = st.columns(2)
    col1.metric("Actual waste proxy", int(card["actual_waste"]))
    col2.metric("Dial In waste proxy", int(card["dialin_waste_proxy"]))
    col3, col4 = st.columns(2)
    col3.metric("Actual sellout rows", int(card["actual_sellouts"]))
    col4.metric("Dial In short proxy", int(card["dialin_short_proxy"]))
    col5, col6, col7 = st.columns(3)
    col5.metric("Attributed rows", int(card["attributed_rows"]))
    col6.metric("Followed", int(card["adhered_rows"]))
    col7.metric("Overridden", int(card["overridden_rows"]))
    override_rows = _recent_override_rows(card["rows"])
    if override_rows:
        with st.expander("Recent overrides"):
            st.dataframe(pd.DataFrame(override_rows), hide_index=True, width="stretch")


def _render_replay_controls(latest_date: date, today: date) -> None:
    """Render sidebar controls for the synthetic replay cursor."""

    replay_date = st.session_state["replay_date"]
    st.sidebar.header("Replay")
    st.sidebar.markdown(
        ui.sidebar_status(
            "Closeout day",
            replay_date,
            _replay_status_caption(replay_date, latest_date, today),
        ),
        unsafe_allow_html=True,
    )
    st.sidebar.markdown(ui.sidebar_action_label("Actions"), unsafe_allow_html=True)
    if st.sidebar.button("Use today", use_container_width=True):
        st.session_state["replay_date"] = today
        st.rerun()
    if st.sidebar.button("Use latest generated day", use_container_width=True):
        st.session_state["replay_date"] = latest_date
        st.rerun()
    if st.sidebar.button("Start 30-day replay", use_container_width=True):
        st.session_state["replay_date"] = latest_date - timedelta(days=30)
        st.rerun()
    if st.sidebar.button("Advance one day", use_container_width=True):
        limit = max(latest_date, today)
        next_date = min(st.session_state["replay_date"] + timedelta(days=1), limit)
        st.session_state["replay_date"] = next_date
        st.rerun()


def _replay_status_caption(replay_date: date, latest_date: date, today: date) -> str:
    """Return a compact caption for the replay cursor status."""

    if replay_date == today:
        return "Using today's operating date."
    if replay_date == latest_date:
        return "Using the latest generated demo day."
    if replay_date < latest_date:
        return "Historical replay mode."
    return "Live test date beyond generated history."


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
        defaults[f"{name}_time_last_sale"] = _time_from_timestamp(row.get("time_last_sale"))
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

    close_minutes = _minutes_from_clock(close_time)
    if close_minutes is None:
        return time(12, 30)
    default_minutes = max(close_minutes - 30, 0)
    hour, minute = divmod(default_minutes, 60)
    return time(hour, minute)


def _time_from_timestamp(value: Any) -> time | None:
    """Return the local clock component from a timestamp-like value."""

    if value is None or pd.isna(value):
        return None
    if isinstance(value, time):
        return value
    timestamp = pd.Timestamp(value)
    return time(int(timestamp.hour), int(timestamp.minute))


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


def _render_correction_audit(database_url: str, account_id: str, location_id: str) -> None:
    """Render recent data correction audit rows."""

    rows = fetch_data_corrections(database_url, account_id, location_id)
    with st.expander("Data corrections"):
        if not rows:
            st.caption("No corrections recorded yet.")
            return
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


def _render_context_panels(context: dict[str, Any], target_date: date) -> None:
    """Render weather, event, and season inputs for one recommendation date."""

    weather_column, event_column, season_column = st.columns(3)
    with weather_column:
        _render_weather_panel(context.get("weather"))
    with event_column:
        _render_event_panel(context.get("events", []))
    with season_column:
        st.markdown("**Season**")
        st.write(_season_label(target_date))
        st.caption(target_date.strftime("%A, %B %-d"))


def _render_weather_panel(weather: dict[str, Any] | None) -> None:
    """Render the target-date weather forecast used by the engine."""

    st.markdown("**Weather**")
    if not weather:
        st.write("Seasonal normal")
        st.caption("No forecast row; confidence should be lower.")
        return
    condition = str(weather.get("condition", "unknown")).title()
    temp = float(weather.get("temp_forecast", 0.0))
    rain = float(weather.get("rain_forecast", 0.0))
    st.write(f"{condition}, {temp:.0f}C")
    st.caption(f"Rain {rain:.1f} mm · made {_format_timestamp(weather.get('forecast_made_at'))}")


def _render_event_panel(events: Any) -> None:
    """Render the strongest event input for the recommendation date."""

    st.markdown("**Events**")
    if not events:
        st.write("None logged")
        st.caption("No event lift applied.")
        return
    first = events[0]
    impact = float(first.get("impact_score", 0.0))
    st.write(str(first.get("event_name", "Local event")))
    st.caption(
        f"{str(first.get('event_type', 'event')).title()} · {_format_lift(1 + impact)} · "
        f"{first.get('confidence', 'Unknown')} confidence"
    )


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


def _import_summary_rows(preview: PosImportPreview) -> list[dict[str, Any]]:
    """Return compact display rows for a POS import preview summary."""

    return [
        {
            "date range": _format_import_date_range(preview),
            "rows read": preview.rows_read,
            "rows imported": preview.rows_imported,
            "rows rejected": preview.rows_rejected,
            "timestamp coverage": _format_percent(preview.timestamp_coverage),
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
            "first sale": _format_timestamp(rollup.first_sale_at),
            "last sale": _format_timestamp(rollup.last_sale_at),
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


def _intraday_sellout_rows(
    rows: list[dict[str, Any]],
    close_time: Any,
) -> list[dict[str, Any]]:
    """Return display rows for category sellouts against the service window."""

    close_minutes = _minutes_from_clock(close_time)
    display_rows: list[dict[str, Any]] = []
    for row in rows:
        sale_time = row.get("time_last_sale")
        sale_minutes = _minutes_from_clock(sale_time)
        minutes_before_close = (
            None if close_minutes is None or sale_minutes is None else close_minutes - sale_minutes
        )
        display_rows.append(
            {
                "category": str(row["category"]).title(),
                "sold": int(row["sold"]),
                "prepared": int(row["prepared"]),
                "last sale": _format_clock(sale_time),
                "before close": _format_minutes_before_close(minutes_before_close),
            }
        )
    return display_rows


def _workflow_rows() -> list[dict[str, str]]:
    """Return the compact daily workflow shown in the app."""

    return [
        {
            "moment": "Before service",
            "action": "Use the Prep tab",
            "input": "Recommendation, service pressure, weather, events",
        },
        {
            "moment": "End of day",
            "action": "Submit Closeout",
            "input": "Drinks sold, sold units, prepared units",
        },
        {
            "moment": "Backfill",
            "action": "Use Import",
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
            "action": "Check Performance",
            "input": "Overrides, corrections, waste and sellout proxies",
        },
    ]


def _format_service_window(hours: dict[str, Any]) -> str:
    """Format one hours row for the service-pressure panel."""

    if not hours.get("is_open"):
        return "Closed"
    open_label = _format_clock(hours.get("open_time"))
    close_label = _format_clock(hours.get("close_time"))
    return f"{open_label}-{close_label}"


def _format_driver(driver: dict[str, Any]) -> str:
    """Format an engine driver as a readable lift instead of a raw multiplier."""

    name = str(driver.get("name", "driver"))
    multiplier = float(driver.get("multiplier", 1.0))
    return f"{name}: {_format_lift(multiplier)}"


def _format_lift(multiplier: float) -> str:
    """Format a multiplier as a signed percentage lift."""

    pct = round((multiplier - 1) * 100)
    if pct > 0:
        return f"+{pct}%"
    if pct < 0:
        return f"{pct}%"
    return "neutral"


def _format_percent(value: float) -> str:
    """Format a ratio as a whole percentage."""

    return f"{round(value * 100)}%"


def _season_label(target_date: date) -> str:
    """Return a compact tourism-season label for the demo calendar."""

    if target_date.month in {6, 7, 8}:
        return "High season"
    if target_date.month in {3, 4, 5, 9, 10, 12}:
        return "Mid season"
    return "Low season"


def _format_timestamp(value: Any) -> str:
    """Format a timestamp-like value for compact Streamlit captions."""

    if value is None or pd.isna(value):
        return "unknown"
    timestamp = pd.Timestamp(value)
    return str(timestamp.strftime("%b %-d %H:%M"))


def _format_clock(value: Any) -> str:
    """Format a time-like value as HH:MM."""

    minutes = _minutes_from_clock(value)
    if minutes is None:
        return "unknown"
    hour, minute = divmod(minutes, 60)
    return f"{hour:02d}:{minute:02d}"


def _minutes_from_clock(value: Any) -> int | None:
    """Convert a timestamp or time value into local minutes after midnight."""

    if value is None or pd.isna(value):
        return None
    if isinstance(value, time):
        return value.hour * 60 + value.minute
    timestamp = pd.Timestamp(value)
    return int(timestamp.hour) * 60 + int(timestamp.minute)


def _format_minutes_before_close(minutes: int | None) -> str:
    """Format a sellout timing delta against close time."""

    if minutes is None:
        return "unknown"
    if minutes < 0:
        return f"{abs(minutes)} min after close"
    if minutes == 0:
        return "at close"
    return f"{minutes} min before close"


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


def _today_for_location(timezone_name: str) -> date:
    """Return today's date in the café timezone, falling back to the system date."""

    try:
        return datetime.now(ZoneInfo(timezone_name)).date()
    except Exception:
        return date.today()


def _style() -> None:
    """Apply the Dial In visual system for a clear operator dashboard."""

    st.markdown(
        """
        <style>
        :root {
            --di-ink: #111111;
            --di-muted: #5f6673;
            --di-line: #e4e7ec;
            --di-paper: #ffffff;
            --di-bg: #f4f6f8;
            --di-mint: #83d7c0;
            --di-green: #22a879;
            --di-yellow: #f2c94c;
        }
        .stApp {
            background:
                linear-gradient(180deg, #ffffff 0%, var(--di-bg) 340px, var(--di-bg) 100%);
            color: var(--di-ink);
        }
        .block-container {
            max-width: 1180px;
            padding-top: 1.25rem;
            padding-bottom: 3rem;
        }
        h1, h2, h3, h4 {
            letter-spacing: 0;
        }
        .di-topbar {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 1rem;
            padding: 0.25rem 0 1.2rem;
        }
        .di-brand {
            font-size: clamp(2rem, 4vw, 4.75rem);
            line-height: 0.92;
            font-weight: 900;
            letter-spacing: 0;
        }
        .di-location {
            margin-top: 0.35rem;
            color: var(--di-muted);
            font-size: 0.98rem;
        }
        .di-date-stack {
            min-width: 190px;
            border: 1px solid var(--di-line);
            border-radius: 8px;
            background: var(--di-paper);
            padding: 0.8rem 0.95rem;
            text-align: right;
            box-shadow: 0 12px 28px rgba(17, 17, 17, 0.05);
        }
        .di-date-stack span {
            display: block;
            color: var(--di-muted);
            font-size: 0.78rem;
        }
        .di-date-stack strong {
            display: block;
            margin-top: 0.15rem;
            font-size: 0.95rem;
        }
        .di-hero {
            position: relative;
            overflow: hidden;
            border: 1px solid #151515;
            border-radius: 8px;
            background:
                radial-gradient(circle at 86% 12%, rgba(131, 215, 192, 0.58), transparent 30%),
                linear-gradient(135deg, #111111 0%, #262626 72%, #1c3f37 100%);
            color: #ffffff;
            padding: clamp(1.4rem, 3vw, 2.4rem);
            margin-bottom: 1rem;
            box-shadow: 0 20px 46px rgba(17, 17, 17, 0.18);
        }
        .di-hero h1 {
            margin: 0.2rem 0 0.5rem;
            font-size: clamp(2rem, 5vw, 4.8rem);
            line-height: 0.95;
            font-weight: 900;
            letter-spacing: 0;
        }
        .di-hero p {
            max-width: 760px;
            color: rgba(255, 255, 255, 0.82);
            font-size: clamp(0.98rem, 1.6vw, 1.18rem);
            margin: 0;
        }
        .di-eyebrow,
        .di-card-label {
            color: var(--di-muted);
            font-size: 0.74rem;
            font-weight: 800;
            letter-spacing: 0;
            text-transform: uppercase;
        }
        .di-hero .di-eyebrow {
            color: var(--di-mint);
        }
        .di-hero-badges,
        .di-chip-row {
            display: flex;
            flex-wrap: wrap;
            gap: 0.45rem;
            margin-top: 1rem;
        }
        .di-hero-badges span,
        .di-chip {
            border-radius: 999px;
            border: 1px solid rgba(17, 17, 17, 0.12);
            background: #ffffff;
            color: var(--di-ink);
            padding: 0.28rem 0.55rem;
            font-size: 0.76rem;
            font-weight: 750;
            white-space: nowrap;
        }
        .di-hero-badges span {
            border-color: rgba(255, 255, 255, 0.18);
            background: rgba(255, 255, 255, 0.12);
            color: #ffffff;
        }
        .di-card,
        div[data-testid="stMetric"] {
            background: var(--di-paper);
            border: 1px solid var(--di-line);
            border-radius: 8px;
            padding: 0.95rem;
            box-shadow: 0 10px 24px rgba(17, 17, 17, 0.045);
        }
        .di-prep-card {
            min-height: 178px;
            margin-bottom: 1rem;
        }
        .di-card-value {
            color: var(--di-ink);
            font-size: 3.2rem;
            line-height: 1;
            font-weight: 900;
            margin-top: 0.25rem;
        }
        .di-context-value {
            color: var(--di-ink);
            font-size: 1.25rem;
            line-height: 1.15;
            font-weight: 850;
            margin-top: 0.35rem;
        }
        .di-card-caption {
            color: var(--di-muted);
            font-size: 0.83rem;
            margin-top: 0.45rem;
        }
        .di-context-card,
        .di-proof-card {
            margin-bottom: 0.7rem;
        }
        .di-flow-card {
            min-height: 128px;
            display: flex;
            flex-direction: column;
            justify-content: center;
        }
        .di-flow-value {
            color: var(--di-ink);
            font-size: clamp(2.1rem, 3vw, 3.35rem);
            line-height: 1.02;
            font-weight: 900;
            margin-top: 0.35rem;
            overflow-wrap: anywhere;
            white-space: normal;
        }
        .di-flow-text {
            font-size: clamp(1.45rem, 2.2vw, 2.5rem);
            line-height: 1.08;
        }
        .di-hours-header {
            min-height: 1.8rem;
            color: var(--di-muted);
            font-size: 0.74rem;
            font-weight: 850;
            text-transform: uppercase;
        }
        .di-hours-day {
            min-height: 2.75rem;
            display: flex;
            align-items: center;
            font-weight: 850;
        }
        div[data-testid="stMetric"] {
            box-shadow: none;
        }
        div[data-testid="stMetricLabel"] {
            color: var(--di-muted);
        }
        .stTabs [data-baseweb="tab-list"] {
            gap: 0.35rem;
            border-bottom: 1px solid var(--di-line);
        }
        .stTabs [data-baseweb="tab"] {
            border-radius: 8px 8px 0 0;
            padding: 0.65rem 0.9rem;
            color: var(--di-muted);
        }
        .stTabs [aria-selected="true"] {
            background: #ffffff;
            color: var(--di-ink);
            font-weight: 800;
        }
        .stButton > button,
        div[data-testid="stFormSubmitButton"] button {
            border-radius: 8px;
            border: 1px solid var(--di-ink);
            background: var(--di-ink);
            color: #ffffff;
            font-weight: 800;
        }
        .stButton > button:hover,
        div[data-testid="stFormSubmitButton"] button:hover {
            border-color: var(--di-green);
            background: var(--di-green);
            color: #ffffff;
        }
        @media (max-width: 700px) {
            .di-topbar {
                align-items: flex-start;
                flex-direction: column;
            }
            .di-date-stack {
                width: 100%;
                text-align: left;
            }
            .di-hero {
                padding: 1.15rem;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(ui.app_styles(), unsafe_allow_html=True)


if __name__ == "__main__":
    main()
