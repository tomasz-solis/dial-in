"""Static smoke tests for the Streamlit entrypoint."""

from __future__ import annotations

import inspect
from datetime import date, datetime, time
from pathlib import Path

import pandas as pd
import pytest
import streamlit as st

import app
from dialin import formatting
from dialin import ui_components as ui
from dialin import views as app_views
from dialin.pos_import import DailySalesRollup, PosImportError, PosImportPreview
from dialin.streamlit_cache import SetupPayload
from dialin.views import closeout, performance, service, setup, today


def test_app_exposes_main() -> None:
    """The Streamlit module should import and expose a main function."""

    assert callable(app.main)


def test_active_view_renderer_calls_only_selected_view(monkeypatch: pytest.MonkeyPatch) -> None:
    """The app should not execute inactive view bodies during one render."""

    calls: list[str] = []
    location = {"location_id": "loc_fadri_main"}

    for view_name in ("today", "closeout", "performance", "service", "setup"):
        view = getattr(app_views, view_name)

        def fake_render(*_: object, _view_name: str = view_name, **__: object) -> None:
            calls.append(_view_name)

        monkeypatch.setattr(view, "render", fake_render)

    app._render_active_view(
        active_view="Service",
        database_url="postgresql://example",
        account_id="acct_fadri",
        username="demo",
        location=location,
        closeout_date=date(2026, 6, 13),
        target_date=date(2026, 6, 14),
    )

    assert calls == ["service"]


def test_demo_refresh_on_load_is_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    """The hosted app should not refresh demo data during startup by default."""

    monkeypatch.delenv("DIALIN_DEMO_REFRESH_ON_LOAD", raising=False)

    assert app._demo_refresh_on_load_enabled() is False

    monkeypatch.setenv("DIALIN_DEMO_REFRESH_ON_LOAD", "true")

    assert app._demo_refresh_on_load_enabled() is True


def test_plotly_charts_use_explicit_keys() -> None:
    """Streamlit Plotly charts should not rely on duplicate-prone auto IDs."""

    source = "".join(
        inspect.getsource(module)
        for module in (closeout, performance, service, setup, today)
    )
    chart_calls = source.count("st.plotly_chart(")

    assert chart_calls > 0
    assert source.count("key=") >= chart_calls


def test_runtime_env_file_prefers_local_settings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Streamlit runtime should prefer the local low-privilege env file."""

    (tmp_path / ".env").write_text("DATABASE_URL=owner\n", encoding="utf-8")
    (tmp_path / ".env.local").write_text("DATABASE_URL=app\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert app._runtime_env_file() == Path(".env.local")


def test_load_runtime_settings_overrides_stale_owner_url(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The app should not depend on a freshly reloaded config module."""

    (tmp_path / ".env.local").write_text(
        "DATABASE_URL=postgresql://dialin_app:app@example.test/dialin\n"
        "MIGRATION_DATABASE_URL=postgresql://dialin_owner:owner@example.test/dialin\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATABASE_URL", "postgresql://neondb_owner:owner@example.test/neondb")

    settings = app._load_runtime_settings()

    assert settings.database_url == "postgresql://dialin_app:app@example.test/dialin"


def test_location_area_corrects_fadri_demo_city() -> None:
    """The Fadri demo header should show the real operating area."""

    assert (
        app._location_area(
            {
                "location_id": "loc_fadri_main",
                "city": "Barcelona",
                "country": "ES",
            }
        )
        == "Cambrils, Tarragona"
    )


def test_location_area_falls_back_to_city_or_country() -> None:
    """Non-demo locations should display their configured city when available."""

    assert app._location_area({"location_id": "loc", "city": "Valencia"}) == "Valencia"
    assert app._location_area({"location_id": "loc", "country": "ES"}) == "ES"


def test_replay_status_caption_labels_cursor_mode() -> None:
    """Replay sidebar status should identify today, demo, and historical modes."""

    today = date(2026, 6, 4)
    latest = date(2026, 6, 3)

    assert app._replay_status_caption(today, latest, today) == "Using today's operating date."
    assert (
        app._replay_status_caption(latest, latest, today)
        == "Using the latest generated demo day."
    )
    assert app._replay_status_caption(date(2026, 5, 1), latest, today) == "Historical replay mode."
    assert (
        app._replay_status_caption(date(2026, 6, 5), latest, today)
        == "Live test date beyond generated history."
    )


def test_app_header_html_tolerates_stale_ui_module(monkeypatch: pytest.MonkeyPatch) -> None:
    """The app header should render even when Streamlit holds an older UI module."""

    monkeypatch.delattr(ui, "app_header")

    html = app._app_header_html(
        brand="Dial In",
        location_name="Fadri Cafe Demo",
        location_area="Cambrils, Tarragona",
        closeout_date=date(2026, 6, 3),
        target_date=date(2026, 6, 4),
    )

    assert html.startswith('<div class="di-topbar">')
    assert "Fadri Cafe Demo" in html
    assert "Cambrils, Tarragona" in html
    assert "2026-06-03" in html
    assert "2026-06-04" in html
    assert "&lt;/div&gt;" not in html


def test_driver_lift_formatting_is_readable() -> None:
    """Driver text should show direction and lift, not raw multipliers."""

    assert formatting.format_driver({"name": "weather", "multiplier": 1.18}) == "weather: +18%"
    assert formatting.format_driver({"name": "rain", "multiplier": 0.94}) == "rain: -6%"
    assert formatting.format_driver({"name": "event", "multiplier": 1.0}) == "event: neutral"


def test_percent_formatting_is_compact() -> None:
    """Service-level ratios should read as whole percentages."""

    assert formatting.format_percent(0.7805) == "78%"


def test_season_label_uses_demo_tourism_bands() -> None:
    """Season labels should be stable for the compact recommendation context panel."""

    assert formatting.season_label(date(2026, 7, 10)) == "High season"
    assert formatting.season_label(date(2026, 10, 10)) == "Mid season"
    assert formatting.season_label(date(2026, 1, 10)) == "Low season"


def test_hero_prep_tiles_keep_categories_separate() -> None:
    """Command Center hero prep values should not collapse into one long headline."""

    html = today._hero_prep_tiles(
        [
            {
                "category": "sweet",
                "recommended_prep": 77,
                "demand_p_lower": 60,
                "demand_p_upper": 84,
                "confidence": "Low",
            },
            {
                "category": "savory",
                "recommended_prep": 26,
                "demand_p_lower": 20,
                "demand_p_upper": 31,
                "confidence": "Medium",
            },
        ]
    )

    assert html.count("di-hero-prep-tile") == 2
    assert "77" in html
    assert "Sweet" in html
    assert "26" in html
    assert "Savory" in html


def test_reason_sentence_names_weather_event_and_direction() -> None:
    """The hero reason should read like plain language, not model jargon."""

    rows = [
        {
            "top_drivers": [
                {"name": "weather forecast", "multiplier": 1.06},
                {"name": "local events", "multiplier": 1.1},
            ]
        }
    ]
    context = {
        "weather": {"condition": "sunny", "temp_forecast": 24.0},
        "events": [{"event_name": "Weekly market"}],
    }

    sentence = today._reason_sentence(rows, context, date(2026, 6, 13))

    assert sentence == "Sunny saturday plus Weekly market — expect a busier day than usual."


def test_reason_sentence_stays_neutral_without_drivers() -> None:
    """A day without external lift should not be sold as busier."""

    sentence = today._reason_sentence(
        [{"top_drivers": []}],
        {"weather": None, "events": []},
        date(2026, 6, 11),
    )

    assert sentence == "A normal Thursday — demand should be close to a typical Thursday."


def test_today_operator_cards_prioritize_action_watch_and_trust() -> None:
    """The daily view should translate model output into owner-ready status."""

    rows = [
        {
            "category": "sweet",
            "recommended_prep": 42,
            "confidence": "Low",
            "risk_flag": "Stockout learning needed",
        },
        {
            "category": "savory",
            "recommended_prep": 18,
            "confidence": "Medium",
            "risk_flag": "Normal",
        },
    ]

    assert today._operator_action(rows) == (
        "Use as advisory",
        "Follow the numbers above, then record a clean closeout.",
    )
    assert today._watch_item(rows, {"events": []}) == (
        "Stockout learning needed",
        "Sweet needs attention.",
    )
    assert today._trust_status(rows) == (
        "Advisory",
        "Useful, but closeout quality matters most today.",
    )
    assert today._closeout_focus(rows) == (
        "Sellout time",
        "If Sweet runs out, record the last sale time.",
    )


def test_service_window_formatting_handles_open_and_closed_days() -> None:
    """Service windows should read cleanly in the intraday panel."""

    assert (
        formatting.format_service_window(
            {"is_open": True, "open_time": time(8, 0), "close_time": time(16, 0)}
        )
        == "08:00-16:00"
    )
    assert formatting.format_service_window({"is_open": False}) == "Closed"


def test_intraday_sellout_rows_show_time_before_close() -> None:
    """Sellout rows should compare last-sale time to closing time."""

    rows = service._intraday_sellout_rows(
        [{"category": "sweet", "sold": 42, "prepared": 42, "time_last_sale": time(13, 30)}],
        time(16, 0),
    )

    assert rows == [
        {
            "category": "Sweet",
            "sold": 42,
            "prepared": 42,
            "last sale": "13:30",
            "before close": "150 min before close",
        }
    ]


def test_stockout_windows_use_known_last_sale_until_close() -> None:
    """Pressure overlays should use explicit last-sale evidence only."""

    windows = service._stockout_windows(
        [
            {"category": "sweet", "time_last_sale": time(12, 20)},
            {"category": "savory", "time_last_sale": None},
        ],
        time(16, 0),
    )

    assert windows == [
        {"category": "Sweet", "start_time": "12:20", "end_time": "16:00"},
    ]


def test_demand_flow_combines_empty_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing pressure and sellout evidence should render one empty panel."""

    markdown_calls: list[str] = []

    def fake_markdown(body: str, **_: object) -> None:
        markdown_calls.append(body)

    monkeypatch.setattr(st, "markdown", fake_markdown)
    monkeypatch.setattr(
        service,
        "_render_pressure_chart",
        lambda *_args, **_kwargs: pytest.fail("pressure chart should not render"),
    )
    monkeypatch.setattr(
        service,
        "_render_sellout_snapshot",
        lambda *_args, **_kwargs: pytest.fail("sellout snapshot should not render"),
    )

    service._render_demand_flow([], [], time(16, 0), "Expected service pressure", "test_key")

    assert len(markdown_calls) == 1
    assert "No demand-flow evidence" in markdown_calls[0]
    assert markdown_calls[0].count("<li>") == 2


def test_workflow_rows_keep_daily_flow_short() -> None:
    """Workflow guidance should stay compact enough for an app tab."""

    rows = setup._workflow_rows()

    assert len(rows) == 6
    assert rows[0]["moment"] == "Before service"


def test_setup_readiness_surfaces_trust_blockers() -> None:
    """Setup should expose default economics and POS import quality at a glance."""

    assert setup._hours_readiness([{"is_open": True}, {"is_open": False}]) == (
        "Opening hours",
        "Ready",
        "1 open days used for recommendations.",
    )
    assert setup._economics_readiness([{"values_source": "default"}]) == (
        "Costs & prices",
        "Need confirmation",
        "Confirm costs to improve confidence.",
    )
    assert setup._pos_readiness([{"rows_imported": 8, "rows_rejected": 2}]) == (
        "POS sales",
        "Review rejects",
        "2 rejected rows need mapping review.",
    )
    assert setup._event_readiness([]) == (
        "Events",
        "None expected",
        "No local event lift is planned.",
    )


def test_setup_readiness_score_names_next_action() -> None:
    """Setup score should convert data readiness into a clear operating mode."""

    payload: SetupPayload = {
        "hours": [{"is_open": True}],
        "economics": [{"values_source": "default"}],
        "recent_imports": [],
        "events": [],
    }

    assert setup._setup_readiness_score(payload) == (
        78,
        "Use with checks",
        ("Confirm economics", "Default costs keep confidence lower."),
    )
    assert setup._operating_mode(78) == "Advisory"

    ready_payload: SetupPayload = {
        "hours": [{"is_open": True}],
        "economics": [{"values_source": "owner_confirmed"}],
        "recent_imports": [{"rows_imported": 100, "rows_rejected": 0}],
        "events": [],
    }
    assert setup._setup_readiness_score(ready_payload)[0] == 100
    assert setup._operating_mode(100) == "Daily guide"


def test_import_summary_rows_show_apply_status() -> None:
    """Import previews should render a compact summary for the operator."""

    preview = PosImportPreview(
        rows_read=3,
        rows_imported=2,
        rows_rejected=1,
        date_start=date(2026, 5, 31),
        date_end=date(2026, 6, 1),
        timestamp_coverage=0.5,
        rollups=(
            DailySalesRollup(date(2026, 5, 31), "drinks", 2, None, None),
        ),
        errors=(
            PosImportError(4, "no category match", {"Item": "Unknown"}),
        ),
        mapped_totals={"drinks": 2, "sweet": 0, "savory": 0},
    )

    assert setup._import_summary_rows(preview) == [
        {
            "date range": "2026-05-31 to 2026-06-01",
            "rows read": 3,
            "rows imported": 2,
            "rows rejected": 1,
            "timestamp coverage": "50%",
            "can apply": "yes",
        }
    ]
    assert setup._import_error_rows(preview) == [
        {"row": 4, "reason": "no category match", "raw row": '{"Item": "Unknown"}'}
    ]


def test_pos_sales_defaults_prefill_sold_when_closeout_is_missing() -> None:
    """Imported category sales should prefill sold values without prepared values."""

    frames = {
        "pos_daily_sales": pd.DataFrame(
            {
                "date": [date(2026, 5, 31), date(2026, 5, 31), date(2026, 5, 31)],
                "category": ["drinks", "sweet", "savory"],
                "units_sold": [120, 42, 16],
            }
        )
    }

    assert closeout._pos_sales_defaults(frames, date(2026, 5, 31)) == {
        "sweet": 42,
        "savory": 16,
    }


def test_scorecard_summary_labels_waste_proxy_delta() -> None:
    """The command center should label proxy savings without overstating accuracy."""

    summary = performance._scorecard_summary(
        {
            "rows": [{"date": date(2026, 5, 31)}],
            "actual_waste": 18,
            "dialin_waste_proxy": 11,
            "attributed_rows": 4,
            "adhered_rows": 3,
        }
    )

    assert summary == {
        "rows": "1",
        "waste_delta_label": "7 fewer units",
        "followed_rate": "75%",
    }


def test_accuracy_frame_uses_observed_proxy_metrics() -> None:
    """Accuracy rows should compare recommendations to observed closeout rows."""

    frame = performance._accuracy_frame(
        [
            {
                "date": date(2026, 5, 31),
                "category": "sweet",
                "recommended_prep": 24,
                "sold": 20,
                "actual_prepared": 26,
                "sold_out": False,
                "adhered": True,
            }
        ]
    )

    assert frame.iloc[0]["actual_waste"] == 6
    assert frame.iloc[0]["dialin_waste_proxy"] == 4
    assert frame.iloc[0]["error_proxy"] == 4
    assert not bool(frame.iloc[0]["short_proxy"])


def test_entry_defaults_preserve_existing_sellout_time() -> None:
    """Closeout defaults should keep previously recorded sellout evidence."""

    frames = {
        "daily_metrics": pd.DataFrame(
            {
                "date": [date(2026, 5, 31)],
                "is_open": [True],
                "drinks_sold": [120],
                "menu_version": ["v1"],
            }
        ),
        "daily_category_metrics": pd.DataFrame(
            {
                "date": [date(2026, 5, 31)],
                "category": ["sweet"],
                "sold": [42],
                "prepared": [42],
                "sold_out": [True],
                "time_last_sale": [datetime(2026, 5, 31, 11, 15)],
            }
        ),
    }

    defaults = closeout._entry_defaults(frames, date(2026, 5, 31))

    assert defaults["sweet_sold_out"] is True
    assert defaults["sweet_time_last_sale"] == time(11, 15)


def test_default_stockout_time_uses_near_close() -> None:
    """The sellout-time default should sit near closing rather than early service."""

    assert closeout._default_stockout_time(time(13, 0)) == time(12, 30)


def test_source_label_removes_hyphenated_title_case() -> None:
    """Traffic source labels should wrap as plain text in metric cards."""

    assert formatting.format_source_label("same-weekday history") == "Same weekday history"


def test_resolved_stockout_time_requires_both_evidence_flags() -> None:
    """A last-sale time should save only when sold-out timing is explicit."""

    sale_time = time(11, 15)

    assert closeout._resolved_stockout_time(True, True, sale_time) == sale_time
    assert closeout._resolved_stockout_time(True, False, sale_time) is None
    assert closeout._resolved_stockout_time(False, True, sale_time) is None
