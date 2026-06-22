"""Precompute recommendation rows for the synthetic demo replay window."""

from __future__ import annotations

import argparse
from datetime import date, timedelta

from dialin.config import load_settings
from dialin.demo_freshness import DEMO_LOCATION_PAIRS
from dialin.repository import (
    fetch_next_open_business_date,
    generate_and_store_recommendations,
    latest_business_date,
)


def precompute_demo_recommendations(days: int, include_tomorrow: bool) -> int:
    """Generate stored recommendations for demo tenants and return row count."""

    settings = load_settings()
    total_rows = 0
    today = date.today()
    for account_id, location_id in DEMO_LOCATION_PAIRS:
        latest = latest_business_date(settings.database_url, account_id, location_id)
        if latest is None:
            continue
        start = latest - timedelta(days=days)
        targets = {start + timedelta(days=offset) for offset in range(1, days + 1)}
        if include_tomorrow:
            next_open = fetch_next_open_business_date(
                settings.database_url, account_id, location_id, today
            )
            targets.add(next_open or today + timedelta(days=1))
        for target_date in sorted(targets):
            results = generate_and_store_recommendations(
                settings.database_url,
                account_id,
                location_id,
                target_date,
            )
            total_rows += len(results)
    return total_rows


def main() -> None:
    """Parse CLI arguments and precompute demo recommendation rows."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--include-tomorrow", action="store_true")
    args = parser.parse_args()

    rows = precompute_demo_recommendations(
        days=args.days,
        include_tomorrow=args.include_tomorrow,
    )
    print(f"precomputed {rows} recommendation rows")


if __name__ == "__main__":
    main()
