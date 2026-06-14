"""Streamlit app for the Dial In synthetic café demo."""

from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import streamlit as st
import streamlit_authenticator as stauth
from dotenv import load_dotenv

from dialin import ui_components as ui
from dialin import views
from dialin.config import Settings, load_settings
from dialin.db import assert_not_owner_connection
from dialin.demo_freshness import ensure_demo_data_fresh
from dialin.streamlit_cache import (
    clear_cached_reads,
    latest_business_date,
    list_locations,
)

VIEW_LABELS = ("Today", "Close out", "How it's doing", "Service", "Setup")


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
    active_view = _render_view_selector()
    _render_active_view(
        active_view=active_view,
        database_url=settings.database_url,
        account_id=account_id,
        username=auth_context["username"],
        location=location,
        closeout_date=closeout_date,
        target_date=target_date,
    )
    _render_replay_controls(latest_date, today)


def _render_view_selector() -> str:
    """Render a single-view selector so inactive views do not execute."""

    active_view = st.radio(
        "View",
        VIEW_LABELS,
        horizontal=True,
        label_visibility="collapsed",
        key="active_view",
    )
    return str(active_view)


def _render_active_view(
    active_view: str,
    database_url: str,
    account_id: str,
    username: str,
    location: dict[str, Any],
    closeout_date: date,
    target_date: date,
) -> None:
    """Render only the selected app view."""

    location_id = str(location["location_id"])
    if active_view == "Today":
        views.today.render(database_url, account_id, location, closeout_date, target_date)
        return
    if active_view == "Close out":
        views.closeout.render(database_url, account_id, username, location, closeout_date)
        return
    if active_view == "How it's doing":
        views.performance.render(database_url, account_id, location_id)
        return
    if active_view == "Service":
        views.service.render(database_url, account_id, location_id, closeout_date, target_date)
        return
    if active_view == "Setup":
        views.setup.render(database_url, account_id, username, location, target_date)
        return
    st.error(f"Unknown view: {active_view}")


def _ensure_demo_freshness_once(
    database_url: str,
    account_id: str,
    location_id: str,
    today: date,
) -> None:
    """Run opt-in demo data freshness once per tenant/location/day in a session."""

    if not _demo_refresh_on_load_enabled():
        return

    session_key = f"demo_freshness:{account_id}:{location_id}:{today.isoformat()}"
    if st.session_state.get(session_key) is True:
        return
    try:
        result = ensure_demo_data_fresh(
            database_url=database_url,
            account_id=account_id,
            location_id=location_id,
            today=today,
        )
    except Exception as exc:
        st.warning(f"Demo data refresh failed, so the app is using loaded data only: {exc}")
        return
    if result.changed:
        clear_cached_reads()
    st.session_state[session_key] = True


def _demo_refresh_on_load_enabled() -> bool:
    """Return true when the app should refresh demo data during page load."""

    value = os.environ.get("DIALIN_DEMO_REFRESH_ON_LOAD")
    if value is None:
        try:
            value = st.secrets["DIALIN_DEMO_REFRESH_ON_LOAD"]
        except (KeyError, FileNotFoundError):
            value = "false"
    return str(value).strip().casefold() in {"1", "true", "yes", "on"}


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
    """Load Streamlit settings, preferring a local env file then app secrets.

    Locally the low-privilege values come from .env.local. On Streamlit Community
    Cloud there is no env file, so the database URL and app role are read from the
    Secrets manager instead.
    """

    env_file = _runtime_env_file()
    if env_file.exists():
        load_dotenv(env_file, override=True)
    _apply_secret_env(("DATABASE_URL", "APP_DATABASE_ROLE"))
    return load_settings(env_file)


def _apply_secret_env(keys: tuple[str, ...]) -> None:
    """Copy top-level Streamlit secrets into the environment when not already set."""

    for key in keys:
        if os.environ.get(key):
            continue
        try:
            value = st.secrets[key]
        except (KeyError, FileNotFoundError):
            continue
        os.environ[key] = str(value)


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


def _today_for_location(timezone_name: str) -> date:
    """Return today's date in the café timezone, falling back to the system date."""

    try:
        return datetime.now(ZoneInfo(timezone_name)).date()
    except Exception:
        return date.today()


def _style() -> None:
    """Apply the Dial In visual system from the single shared stylesheet."""

    st.markdown(ui.app_styles(), unsafe_allow_html=True)


if __name__ == "__main__":
    main()
