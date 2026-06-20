"""Pure assembly of the exportable pilot report (Phase 12; PRD sections 14, 14.1).

This module does no I/O. The performance view gathers already-computed inputs
(pilot windows and profile, per-category model gates, the observed scorecard) and
this builder turns them into honest Markdown. It deliberately separates observed
facts, modelled estimates, assumptions, and synthetic-demo behaviour, and never
emits a validated-ROI claim.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from dialin.repository._common import _as_date
from dialin.repository.pilot import PILOT_CHECKLIST_FIELDS


def summarize_rows(rows: list[dict[str, Any]]) -> dict[str, int]:
    """Aggregate scorecard rows into waste, sellout, and adherence proxies."""

    waste_proxy = sum(max(int(row["recommended_prep"]) - int(row["sold"]), 0) for row in rows)
    actual_waste = sum(max(int(row["actual_prepared"]) - int(row["sold"]), 0) for row in rows)
    sellouts = sum(1 for row in rows if row.get("sold_out"))
    adhered = sum(1 for row in rows if row.get("adhered") is True)
    overridden = sum(1 for row in rows if row.get("adhered") is False)
    dates = {_row_date(row) for row in rows if row.get("date") is not None}
    return {
        "days": len(dates) if dates else len(rows),
        "dialin_waste_proxy": waste_proxy,
        "actual_waste": actual_waste,
        "sellouts": sellouts,
        "adhered": adhered,
        "overridden": overridden,
    }


def build_pilot_report_markdown(
    *,
    account_label: str,
    location_label: str,
    generated_on: date,
    windows: list[dict[str, Any]],
    profile: dict[str, Any] | None,
    gates: list[dict[str, Any]],
    scorecard_rows: list[dict[str, Any]],
    synthetic: bool,
) -> str:
    """Return a Markdown pilot report bundling windows, gates, and outcomes."""

    lines: list[str] = []
    lines.append(f"# Dial In pilot report — {account_label}")
    lines.append("")
    lines.append(f"- Location: {location_label}")
    lines.append(f"- Generated: {generated_on.isoformat()}")
    if synthetic:
        lines.append(
            "- **Demo data:** this account runs on synthetic data. Numbers below show the "
            "workflow, not validated business impact."
        )
    lines.append("")
    lines.append(
        "> Honest framing: figures are an *observed* replay proxy and *modelled* estimates, "
        "not validated ROI. Waste and stockouts trade off along one curve (PRD section 6.2)."
    )
    lines.append("")

    lines.extend(_windows_section(windows, scorecard_rows))
    lines.extend(_gates_section(gates))
    lines.extend(_profile_section(profile))
    lines.extend(_caveats_section())
    return "\n".join(lines)


def _windows_section(
    windows: list[dict[str, Any]], scorecard_rows: list[dict[str, Any]]
) -> list[str]:
    """Render baseline vs live windows with their partitioned outcome proxies."""

    lines = ["## Phase windows and outcomes", ""]
    if not windows:
        lines.append("_No pilot windows defined yet. Add a baseline and a live window._")
        lines.append("")
        return lines
    lines.append(
        "| Phase | Start | End | Open days | Sellout rows | Waste proxy (units) | Followed |"
    )
    lines.append("|---|---|---|---|---|---|---|")
    for window in windows:
        phase = str(window["phase"])
        start = _as_date(window["start_date"])
        end = None if window["end_date"] is None else _as_date(window["end_date"])
        matching = [
            row
            for row in scorecard_rows
            if start <= _row_date(row) and (end is None or _row_date(row) <= end)
        ]
        summary = summarize_rows(matching)
        display_end = window["end_date"] or "open"
        lines.append(
            f"| {phase} | {window['start_date']} | {display_end} | {summary['days']} | "
            f"{summary['sellouts']} | {summary['dialin_waste_proxy']} | "
            f"{summary['adhered']}/{summary['adhered'] + summary['overridden']} |"
        )
    lines.append("")
    return lines


def _gates_section(gates: list[dict[str, Any]]) -> list[str]:
    """Render the per-category shadow/live model gates."""

    lines = ["## Model gates (per category)", ""]
    if not gates:
        lines.append("_No matched recommendation history yet to evaluate gates._")
        lines.append("")
        return lines
    lines.append("| Category | Status | Days | Beats baselines | Coverage | Signed error |")
    lines.append("|---|---|---|---|---|---|")
    for gate in gates:
        coverage = gate.get("range_coverage")
        coverage_text = "n/a" if coverage is None else f"{float(coverage):.0%}"
        lines.append(
            f"| {gate['category']} | {gate['status']} | {gate['evaluated_days']} | "
            f"{'yes' if gate.get('beats_baselines') else 'no'} | {coverage_text} | "
            f"{gate.get('signed_error')} |"
        )
    lines.append("")
    return lines


def _profile_section(profile: dict[str, Any] | None) -> list[str]:
    """Render the pilot setup checklist with its confirmation source."""

    lines = ["## Pilot setup checklist", ""]
    if not profile:
        lines.append("_Pilot setup not completed. Values fall back to defaults._")
        lines.append("")
        return lines
    responses = profile.get("responses") or {}
    source = profile.get("values_source", "default")
    lines.append(f"Source: **{source}**")
    lines.append("")
    for field in PILOT_CHECKLIST_FIELDS:
        value = responses.get(field["key"], "—")
        lines.append(f"- {field['label']}: {value}")
    lines.append("")
    return lines


def _caveats_section() -> list[str]:
    """Render the observed/estimated/assumed/synthetic honesty footer."""

    return [
        "## What is observed, estimated, assumed",
        "",
        "- **Observed:** sold and prepared counts, sellout days, adherence.",
        "- **Estimated:** de-censored demand on sold-out days, expected mis-prep cost, "
        "calibration — all with uncertainty.",
        "- **Assumed:** any category economics still on defaults, plus unconfirmed events.",
        "- **Not claimed:** validated ROI. A pilot this short cannot prove savings; it can "
        "only show whether the workflow and direction look credible (PRD section 6.5).",
        "",
    ]


def _row_date(row: dict[str, Any]) -> date:
    """Coerce a scorecard row's date to a ``date``."""

    value = row["date"]
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])
