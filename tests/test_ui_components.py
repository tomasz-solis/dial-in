"""Tests for reusable UI component helpers."""

from __future__ import annotations

from pathlib import Path

from dialin import ui_components as ui


def test_text_escapes_html() -> None:
    """Display text should be escaped before it enters HTML fragments."""

    assert (
        ui.text("<script>alert('x')</script>")
        == "&lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt;"
    )


def test_metric_card_contains_stable_classes_and_escaped_text() -> None:
    """Metric cards should expose stable classes and escape dynamic labels."""

    html = ui.metric_card("<Label>", "Same weekday history", "Observed <source>")

    assert "di-metric-card" in html
    assert "&lt;Label&gt;" in html
    assert "Observed &lt;source&gt;" in html


def test_card_grid_wraps_safe_card_fragments() -> None:
    """Card grids should provide stable classes for compact evidence strips."""

    html = ui.card_grid((ui.proof_card("Rows", "52"), ui.proof_card("Rate", "75%")), columns=2)

    assert "di-card-grid" in html
    assert "di-card-grid-2" in html
    assert html.count("di-proof-card") == 2
    assert "\n" not in html
    assert "    <div" not in html


def test_hero_prep_tile_splits_number_from_category() -> None:
    """Hero prep tiles should keep the decision readable and escape labels."""

    html = ui.hero_prep_tile("<Sweet>", 77, "60-84", "Low <confidence>")

    assert "di-hero-prep-tile" in html
    assert "di-hero-prep-number" in html
    assert "77" in html
    assert "&lt;Sweet&gt;" in html
    assert "Low &lt;confidence&gt;" in html


def test_command_hero_uses_prep_grid_and_escapes_copy() -> None:
    """The hero should render prep tiles below a short escaped headline."""

    tile_html = ui.hero_prep_tile("Savory", 26, "20-31", "Medium")
    html = ui.command_hero(
        prep_summary="Prep <today>",
        subtitle="Thursday <service>",
        prep_tiles_html=tile_html,
        badges_html=ui.badge("Low <confidence>", tone="dark"),
        driver_html=ui.chip("High season"),
        image_uri="",
    )

    assert "di-hero-prep-grid" in html
    assert "di-hero-prep-tile" in html
    assert "Prep &lt;today&gt;" in html
    assert "Thursday &lt;service&gt;" in html
    assert "Low &lt;confidence&gt;" in html


def test_date_stack_separates_labels_from_dates() -> None:
    """The header date card should render two compact label-value rows."""

    html = ui.date_stack("2026-06-03", "<2026-06-04>")

    assert html.count('<div class="di-date-row') == 2
    assert "\n" not in html
    assert "Closeout" in html
    assert "Prep" in html
    assert "2026-06-03" in html
    assert "&lt;2026-06-04&gt;" in html


def test_app_header_is_one_safe_fragment() -> None:
    """The app header should not leave loose closing tags in Streamlit."""

    html = ui.app_header(
        brand="<Dial>",
        location_name="Fadri <Demo>",
        location_area="Cambrils",
        closeout_date="2026-06-03",
        target_date="2026-06-04",
    )

    assert html.startswith('<div class="di-topbar">')
    assert html.endswith("</div>")
    assert "\n" not in html
    assert "&lt;Dial&gt;" in html
    assert "Fadri &lt;Demo&gt;" in html
    assert "&lt;/div&gt;" not in html


def test_sidebar_helpers_escape_display_values() -> None:
    """Sidebar panels should escape names, values, and captions."""

    user_html = ui.sidebar_user("<Demo>")
    status_html = ui.sidebar_status("Closeout", "<2026-06-03>", "Replay <mode>")
    action_html = ui.sidebar_action_label("Action <buttons>")

    assert "di-sidebar-user" in user_html
    assert "&lt;Demo&gt;" in user_html
    assert "di-sidebar-panel" in status_html
    assert "&lt;2026-06-03&gt;" in status_html
    assert "Replay &lt;mode&gt;" in status_html
    assert "di-sidebar-action-label" in action_html
    assert "Action &lt;buttons&gt;" in action_html


def test_closeout_status_and_form_sections_are_safe() -> None:
    """Closeout workflow helpers should expose stable classes and escape text."""

    status_html = ui.closeout_status(
        business_date="<2026-06-03>",
        target_date="2026-06-04",
        mode="Replay",
        service_window="08:00-16:00",
    )
    section_html = ui.form_section("Service <totals>", "Observed <counts>")

    assert status_html.count("di-closeout-status-item") == 4
    assert "&lt;2026-06-03&gt;" in status_html
    assert "di-form-section" in section_html
    assert "Service &lt;totals&gt;" in section_html
    assert "Observed &lt;counts&gt;" in section_html


def test_empty_state_list_renders_one_panel_with_escaped_bullets() -> None:
    """Grouped empty states should avoid stacked panels for related missing evidence."""

    html = ui.empty_state_list("No <evidence>", ("No curve", "No <sellout>"))

    assert "di-empty-state-list" in html
    assert html.count("<li>") == 2
    assert "No &lt;evidence&gt;" in html
    assert "No &lt;sellout&gt;" in html


def test_badge_rejects_unknown_tone() -> None:
    """Unknown badge tones should fall back to neutral styling."""

    assert "di-badge-neutral" in ui.badge("Ready", tone="made-up")


def test_image_data_uri_reads_local_image(tmp_path: Path) -> None:
    """Local assets should be embedded as data URIs instead of hotlinked."""

    image_path = tmp_path / "tiny.jpg"
    image_path.write_bytes(b"\xff\xd8\xff\xd9")

    assert ui.image_data_uri(image_path).startswith("data:image/jpeg;base64,")


def test_app_styles_exposes_core_layout_classes() -> None:
    """The shared CSS should define the product shell classes used by app.py."""

    styles = ui.app_styles()

    assert ".di-hero" in styles
    assert ".di-date-stack" in styles
    assert ".di-date-row" in styles
    assert ".di-sidebar-panel" in styles
    assert ".di-sidebar-action-label" in styles
    assert ".di-closeout-status" in styles
    assert ".di-form-section" in styles
    assert ".di-card-grid" in styles
    assert ".di-empty-state-list" in styles
    assert "div[data-testid=\"stButton\"] button" in styles
    assert "margin: 0.7rem 0 !important;" in styles
    assert "box-shadow: 12px 0 34px" in styles
    assert ".di-hours-day" in styles
