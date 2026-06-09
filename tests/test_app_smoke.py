"""Static smoke tests for the Streamlit entrypoint."""

from __future__ import annotations

import inspect
from datetime import date, datetime, time
from pathlib import Path

import pandas as pd
import pytest
import streamlit as st

import app
from dialin import ui_components as ui
from dialin.pos_import import DailySalesRollup, PosImportError, PosImportPreview


def test_app_exposes_main() -> None:
    """The Streamlit module should import and expose a main function."""

    assert callable(app.main)


def test_plotly_charts_use_explicit_keys() -> None:
    """Streamlit Plotly charts should not rely on duplicate-prone auto IDs."""

    source = inspect.getsource(app)
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

    assert app._format_driver({"name": "weather", "multiplier": 1.18}) == "weather: +18%"
    assert app._format_driver({"name": "rain", "multiplier": 0.94}) == "rain: -6%"
    assert app._format_driver({"name": "event", "multiplier": 1.0}) == "event: neutral"


def test_percent_formatting_is_compact() -> None:
    """Service-level ratios should read as whole percentages."""

    assert app._format_percent(0.7805) == "78%"


def test_season_label_uses_demo_tourism_bands() -> None:
    """Season labels should be stable for the compact recommendation context panel."""

    assert app._season_label(date(2026, 7, 10)) == "High season"
    assert app._season_label(date(2026, 10, 10)) == "Mid season"
    assert app._season_label(date(2026, 1, 10)) == "Low season"


def test_hero_prep_tiles_keep_categories_separate() -> None:
    """Command Center hero prep values should not collapse into one long headline."""

    html = app._hero_prep_tiles(
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


def test_command_driver_chips_skip_neutral_context() -> None:
    """The hero should show signal, not neutral placeholder text."""

    html = app._command_driver_chips(
        [
            {
                "top_drivers": [
                    {"name": "sellout correction", "multiplier": 1.2},
                    {"name": "sweet attach", "multiplier": 1.37},
                    {"name": "extra driver", "multiplier": 1.1},
                ]
            }
        ],
        {"weather": None, "events": []},
        date(2026, 7, 10),
    )

    assert "High season" in html
    assert "Seasonal normal" not in html
    assert "No event logged" not in html
    assert html.count("di-chip") <= 5


def test_service_window_formatting_handles_open_and_closed_days() -> None:
    """Service windows should read cleanly in the intraday panel."""

    assert (
        app._format_service_window(
            {"is_open": True, "open_time": time(8, 0), "close_time": time(16, 0)}
        )
        == "08:00-16:00"
    )
    assert app._format_service_window({"is_open": False}) == "Closed"


def test_intraday_sellout_rows_show_time_before_close() -> None:
    """Sellout rows should compare last-sale time to closing time."""

    rows = app._intraday_sellout_rows(
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


def test_sellout_timing_frame_skips_missing_timestamps() -> None:
    """Sellout timing charts should use only explicit last-sale evidence."""

    frame = app._sellout_timing_frame(
        [
            {"category": "sweet", "time_last_sale": time(11, 30)},
            {"category": "savory", "time_last_sale": None},
        ],
        time(13, 0),
    )

    assert frame.to_dict("records") == [
        {
            "category": "Sweet",
            "minutes_before_close": 90,
            "last_sale": "11:30",
            "severity_color": "#d24b3f",
        }
    ]


def test_stockout_windows_use_known_last_sale_until_close() -> None:
    """Pressure overlays should use explicit last-sale evidence only."""

    windows = app._stockout_windows(
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
        app,
        "_render_pressure_chart",
        lambda *_args, **_kwargs: pytest.fail("pressure chart should not render"),
    )
    monkeypatch.setattr(
        app,
        "_render_sellout_snapshot",
        lambda *_args, **_kwargs: pytest.fail("sellout snapshot should not render"),
    )

    app._render_demand_flow([], [], time(16, 0), "Expected service pressure", "test_key")

    assert len(markdown_calls) == 1
    assert "No demand-flow evidence" in markdown_calls[0]
    assert markdown_calls[0].count("<li>") == 2


def test_workflow_rows_keep_daily_flow_short() -> None:
    """Workflow guidance should stay compact enough for an app tab."""

    rows = app._workflow_rows()

    assert len(rows) == 6
    assert rows[0]["moment"] == "Before service"


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

    assert app._import_summary_rows(preview) == [
        {
            "date range": "2026-05-31 to 2026-06-01",
            "rows read": 3,
            "rows imported": 2,
            "rows rejected": 1,
            "timestamp coverage": "50%",
            "can apply": "yes",
        }
    ]
    assert app._import_error_rows(preview) == [
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

    assert app._pos_sales_defaults(frames, date(2026, 5, 31)) == {
        "sweet": 42,
        "savory": 16,
    }


def test_scorecard_summary_labels_waste_proxy_delta() -> None:
    """The command center should label proxy savings without overstating accuracy."""

    summary = app._scorecard_summary(
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

    frame = app._accuracy_frame(
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

    defaults = app._entry_defaults(frames, date(2026, 5, 31))

    assert defaults["sweet_sold_out"] is True
    assert defaults["sweet_time_last_sale"] == time(11, 15)


def test_default_stockout_time_uses_near_close() -> None:
    """The sellout-time default should sit near closing rather than early service."""

    assert app._default_stockout_time(time(13, 0)) == time(12, 30)


def test_source_label_removes_hyphenated_title_case() -> None:
    """Traffic source labels should wrap as plain text in metric cards."""

    assert app._format_source_label("same-weekday history") == "Same weekday history"


def test_resolved_stockout_time_requires_both_evidence_flags() -> None:
    """A last-sale time should save only when sold-out timing is explicit."""

    sale_time = time(11, 15)

    assert app._resolved_stockout_time(True, True, sale_time) == sale_time
    assert app._resolved_stockout_time(True, False, sale_time) is None
    assert app._resolved_stockout_time(False, True, sale_time) is None
