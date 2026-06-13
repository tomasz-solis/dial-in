"""Keep the synthetic demo tenants current up to today.

The Streamlit app already refreshes demo data on load (see
``dialin.demo_freshness``), so a shared link self-heals when someone opens it.
Run this script to *pre-warm* that work — e.g. on a schedule — so the first
visitor sees current data without waiting for the on-load pass, or so the demo
is current even if nobody has opened it for a while.

It is idempotent: it only appends missing calendar days and re-generates recent
recommendations, never overwriting real operator entries.

Usage::

    uv run python scripts/refresh_demo_data.py
    uv run python scripts/refresh_demo_data.py --today 2026-06-20

Uses ``DATABASE_URL`` (the low-privilege app role is sufficient; row-level
security is satisfied because the freshness routine scopes every write to its
tenant).
"""

from __future__ import annotations

import argparse
from datetime import date

from dialin.config import load_settings, mask_database_url
from dialin.demo_freshness import DEMO_LOCATION_PAIRS, ensure_demo_data_fresh


def refresh_demo_data(today: date) -> int:
    """Extend demo history to ``today`` and refresh recommendations for all demo tenants."""

    settings = load_settings()
    print(f"refreshing demo data in {mask_database_url(settings.database_url)} up to {today}")
    total_rows = 0
    for account_id, location_id in DEMO_LOCATION_PAIRS:
        result = ensure_demo_data_fresh(
            database_url=settings.database_url,
            account_id=account_id,
            location_id=location_id,
            today=today,
        )
        total_rows += result.recommendation_rows
        print(
            f"  {account_id}/{location_id}: "
            f"+{len(result.observed_dates)} observed days, "
            f"+{len(result.context_dates)} context days, "
            f"{result.recommendation_rows} recommendation rows"
        )
    return total_rows


def main() -> None:
    """Parse CLI options and refresh demo data up to today (or a chosen date)."""

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--today",
        type=date.fromisoformat,
        default=date.today(),
        help="Treat this ISO date as today (defaults to the system date).",
    )
    args = parser.parse_args()
    rows = refresh_demo_data(args.today)
    print(f"done — {rows} recommendation rows refreshed")


if __name__ == "__main__":
    main()
