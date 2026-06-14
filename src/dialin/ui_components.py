"""Reusable Streamlit UI fragments for the Dial In app."""

from __future__ import annotations

from collections.abc import Iterable
from html import escape
from typing import Any

from dialin.styles import app_styles as app_styles


def text(value: Any) -> str:
    """Return escaped display text for safe HTML rendering."""

    return escape(str(value))


def badge(label: Any, tone: str = "neutral") -> str:
    """Return one status badge with a constrained tone class."""

    safe_tone = tone if tone in {"neutral", "good", "warn", "risk", "dark"} else "neutral"
    return f'<span class="di-badge di-badge-{safe_tone}">{text(label)}</span>'


def chip(label: Any) -> str:
    """Return one compact evidence chip."""

    return f'<span class="di-chip">{text(label)}</span>'


def badges(labels: Iterable[Any], tone: str = "neutral") -> str:
    """Return multiple badges as adjacent HTML spans."""

    return "".join(badge(label, tone=tone) for label in labels)


def card_grid(cards_html: Iterable[str], columns: int = 3) -> str:
    """Return a responsive grid for already-rendered safe card fragments."""

    safe_columns = columns if columns in {2, 3, 4} else 3
    cards = "".join(_compact_html_fragment(card) for card in cards_html)
    return (
        f'<div class="di-card-grid di-card-grid-{safe_columns}">'
        f"{cards}"
        "</div>"
    )


def _compact_html_fragment(fragment: str) -> str:
    """Return one HTML fragment without Markdown-inducing indentation."""

    return "".join(line.strip() for line in str(fragment).splitlines())


def section_heading(title: Any, kicker: Any | None = None) -> str:
    """Return a compact section heading block."""

    kicker_html = "" if kicker is None else f'<div class="di-section-kicker">{text(kicker)}</div>'
    return f"""
    <div class="di-section-heading">
      {kicker_html}
      <h2>{text(title)}</h2>
    </div>
    """


def metric_card(label: Any, value: Any, caption: Any | None = None, tone: str = "light") -> str:
    """Return a stable metric card that wraps text instead of clipping it."""

    safe_tone = tone if tone in {"light", "dark", "mint"} else "light"
    caption_html = "" if caption is None else f'<div class="di-card-caption">{text(caption)}</div>'
    return f"""
    <div class="di-card di-metric-card di-card-{safe_tone}">
      <div class="di-card-label">{text(label)}</div>
      <div class="di-metric-value">{text(value)}</div>
      {caption_html}
    </div>
    """


def proof_card(label: Any, value: Any, caption: Any | None = None) -> str:
    """Return a compact proof card for the Command Center side rail."""

    caption_html = "" if caption is None else f'<div class="di-card-caption">{text(caption)}</div>'
    return f"""
    <div class="di-card di-proof-card">
      <div class="di-card-label">{text(label)}</div>
      <div class="di-context-value">{text(value)}</div>
      {caption_html}
    </div>
    """


def context_card(title: Any, value: Any, caption: Any) -> str:
    """Return one recommendation context card."""

    return f"""
    <div class="di-card di-context-card">
      <div class="di-card-label">{text(title)}</div>
      <div class="di-context-value">{text(value)}</div>
      <div class="di-card-caption">{text(caption)}</div>
    </div>
    """


def date_stack(closeout_date: Any, target_date: Any) -> str:
    """Return the compact active-date status used in the app header."""

    return (
        '<div class="di-date-stack" aria-label="Active planning dates">'
        '<div class="di-date-row">'
        "<span>Closeout</span>"
        f"<strong>{text(closeout_date)}</strong>"
        "</div>"
        '<div class="di-date-row di-date-row-primary">'
        "<span>Prep</span>"
        f"<strong>{text(target_date)}</strong>"
        "</div>"
        "</div>"
    )


def app_header(
    brand: Any,
    location_name: Any,
    location_area: Any,
    closeout_date: Any,
    target_date: Any,
) -> str:
    """Return the complete app header as one safe HTML fragment."""

    return (
        '<div class="di-topbar">'
        "<div>"
        f'<div class="di-brand">{text(brand)}</div>'
        f'<div class="di-location">{text(location_name)} · {text(location_area)}</div>'
        "</div>"
        f"{date_stack(closeout_date, target_date)}"
        "</div>"
    )


def sidebar_user(name: Any) -> str:
    """Return the signed-in user block for the sidebar."""

    return (
        '<div class="di-sidebar-user">'
        '<span>Signed in</span>'
        f"<strong>{text(name)}</strong>"
        "</div>"
    )


def sidebar_status(title: Any, value: Any, caption: Any | None = None) -> str:
    """Return a compact sidebar status panel."""

    caption_html = "" if caption is None else f"<p>{text(caption)}</p>"
    return (
        '<div class="di-sidebar-panel">'
        f'<div class="di-sidebar-kicker">{text(title)}</div>'
        f"<strong>{text(value)}</strong>"
        f"{caption_html}"
        "</div>"
    )


def sidebar_action_label(label: Any) -> str:
    """Return the small divider label above sidebar action buttons."""

    return f'<div class="di-sidebar-action-label">{text(label)}</div>'


def command_hero(
    prep_summary: Any,
    subtitle: Any,
    prep_tiles_html: str,
    badges_html: str,
    reason: Any,
) -> str:
    """Return the decision-first hero: numbers, range, and one plain reason."""

    return f"""
    <div class="di-hero">
      <div class="di-hero-copy">
        <div class="di-eyebrow">Prep decision</div>
        <h1>{text(prep_summary)}</h1>
        <p>{text(subtitle)}</p>
        <div class="di-hero-prep-grid">{prep_tiles_html}</div>
        <div class="di-hero-badges">{badges_html}</div>
        <div class="di-hero-reason">{text(reason)}</div>
      </div>
    </div>
    """


def hero_prep_tile(
    category: Any,
    recommended: int,
    demand_range: Any,
    confidence: Any,
) -> str:
    """Return one readable prep tile for the Command Center hero."""

    return f"""
    <div class="di-hero-prep-tile">
      <div class="di-hero-prep-number">{recommended}</div>
      <div>
        <div class="di-hero-prep-category">{text(category)}</div>
        <div class="di-hero-prep-caption">
          Likely sells {text(demand_range)} · {text(confidence)} confidence
        </div>
      </div>
    </div>
    """


def empty_state(title: Any, body: Any) -> str:
    """Return a quiet empty-state panel."""

    return f"""
    <div class="di-empty-state">
      <strong>{text(title)}</strong>
      <span>{text(body)}</span>
    </div>
    """


def empty_state_list(title: Any, items: Iterable[Any]) -> str:
    """Return one empty-state panel with a short bullet list."""

    bullets = "".join(f"<li>{text(item)}</li>" for item in items)
    return (
        '<div class="di-empty-state di-empty-state-list">'
        f"<strong>{text(title)}</strong>"
        f"<ul>{bullets}</ul>"
        "</div>"
    )


def closeout_status(
    business_date: Any,
    target_date: Any,
    mode: Any,
    service_window: Any,
) -> str:
    """Return the closeout workflow status strip."""

    items = (
        ("Closeout", business_date),
        ("Generates", target_date),
        ("Mode", mode),
        ("Service", service_window),
    )
    rows = "".join(
        (
            '<div class="di-closeout-status-item">'
            f"<span>{text(label)}</span>"
            f"<strong>{text(value)}</strong>"
            "</div>"
        )
        for label, value in items
    )
    return f'<div class="di-closeout-status">{rows}</div>'


def form_section(title: Any, caption: Any | None = None) -> str:
    """Return a compact section divider for Streamlit forms."""

    caption_html = "" if caption is None else f"<p>{text(caption)}</p>"
    return (
        '<div class="di-form-section">'
        f"<strong>{text(title)}</strong>"
        f"{caption_html}"
        "</div>"
    )
