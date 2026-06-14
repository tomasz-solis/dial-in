"""Today tab: the decision-first prep recommendation view."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import streamlit as st

from dialin import ui_components as ui
from dialin.formatting import (
    format_driver,
    format_lift,
    format_percent,
    format_service_window,
    format_timestamp,
    season_label,
)
from dialin.streamlit_cache import (
    fetch_today_payload,
)


def render(
    database_url: str,
    account_id: str,
    location: dict[str, Any],
    closeout_date: date,
    target_date: date,
) -> None:
    """Render the main daily decision view for the operator."""

    location_id = str(location["location_id"])
    payload = fetch_today_payload(database_url, account_id, location_id, target_date)
    recommendation_rows = payload["recommendations"]
    context = payload["context"]
    flow = payload["flow"]

    if not recommendation_rows:
        st.info(
            f"No prep recommendation is stored for {target_date}. "
            f"Close out {closeout_date} to generate the next decision."
        )
        return

    _render_recommendation_hero(recommendation_rows, context, flow, target_date)
    with st.expander("Why these numbers"):
        _render_context_cards(context, target_date)
        _render_why_details(recommendation_rows)


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
    service_window = format_service_window(flow["hours"])
    subtitle_parts = [f"{target_date.strftime('%A, %b')} {target_date.day}", service_window]
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
            reason=_reason_sentence(rows, context, target_date),
        ),
        unsafe_allow_html=True,
    )


def _reason_sentence(
    rows: list[dict[str, Any]],
    context: dict[str, Any],
    target_date: date,
) -> str:
    """Return one plain-language reason for the recommendation level."""

    day = target_date.strftime("%A")
    weather = context.get("weather")
    events = context.get("events", [])
    condition = str(weather.get("condition", "")).strip() if weather else ""
    if condition and condition.casefold() != "seasonal normal":
        subject = f"{condition.title()} {day.lower()}"
    else:
        subject = f"A normal {day}"
    if events:
        subject += f" plus {events[0].get('event_name', 'a local event')}"

    lift = _external_lift(rows)
    if lift > 1.04:
        outlook = "expect a busier day than usual"
    elif lift < 0.96:
        outlook = "expect a quieter day than usual"
    else:
        outlook = f"demand should be close to a typical {day}"
    return f"{subject} — {outlook}."


def _external_lift(rows: list[dict[str, Any]]) -> float:
    """Return the combined weather and event lift from stored drivers."""

    lift = 1.0
    seen: set[str] = set()
    for row in rows:
        drivers = row.get("top_drivers", [])
        if isinstance(drivers, str):
            drivers = json.loads(drivers)
        for driver in drivers:
            name = str(driver.get("name", ""))
            if name in {"weather forecast", "local events"} and name not in seen:
                seen.add(name)
                lift *= float(driver.get("multiplier", 1.0))
    return lift


def _render_why_details(rows: list[dict[str, Any]]) -> None:
    """Render per-category ranges, service levels, and drivers on demand."""

    for row in rows:
        st.markdown(
            f"**{str(row['category']).title()}** — likely sells "
            f"{int(row['demand_p_lower'])}-{int(row['demand_p_upper'])} "
            f"(median {int(row['demand_p50'])}) · prep set at the "
            f"{format_percent(float(row['service_quantile']))} service level "
            f"· {row['confidence']} confidence"
        )
        st.markdown(
            f'<div class="di-chip-row">{_driver_chips(row.get("top_drivers", []))}</div>',
            unsafe_allow_html=True,
        )


def _render_context_cards(context: dict[str, Any], target_date: date) -> None:
    """Render the weather, event, and season inputs as compact cards."""

    weather = context.get("weather")
    events = context.get("events", [])
    season_caption = f"{target_date.strftime('%A, %B')} {target_date.day}"
    cards = [
        ("Weather", _weather_summary(weather), _weather_detail(weather)),
        ("Events", _event_summary(events), _event_detail(events)),
        ("Season", season_label(target_date), season_caption),
    ]
    st.markdown(
        ui.card_grid(
            (ui.context_card(title, value, caption) for title, value, caption in cards),
            columns=3,
        ),
        unsafe_allow_html=True,
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


def _weather_detail(weather: dict[str, Any] | None) -> str:
    """Return compact weather detail text for context cards."""

    if not weather:
        return "No forecast row; lower confidence."
    rain = float(weather.get("rain_forecast", 0.0))
    return f"Rain {rain:.1f} mm · made {format_timestamp(weather.get('forecast_made_at'))}"


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
        f"{str(first.get('event_type', 'event')).title()} · {format_lift(1 + impact)} · "
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
        label = format_driver(driver)
        chips.append(ui.chip(label))
    return "".join(chips)
