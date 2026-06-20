"""Tests for the modelled intraday sellout / lost-sales estimate (PRD 10.10, 12)."""

from __future__ import annotations

from datetime import time

from dialin.repository.intraday import (
    cumulative_traffic_fraction,
    estimate_lost_sales,
)

# Flat half-hour curve, 09:00-11:00, 10 expected drinks per bucket (40 total).
FLAT_CURVE = [
    {"time": "09:00", "expected_drinks": 10},
    {"time": "09:30", "expected_drinks": 10},
    {"time": "10:00", "expected_drinks": 10},
    {"time": "10:30", "expected_drinks": 10},
]


def test_cumulative_fraction_runs_zero_to_one() -> None:
    assert cumulative_traffic_fraction(FLAT_CURVE, 9 * 60) == 0.0
    assert cumulative_traffic_fraction(FLAT_CURVE, 10 * 60) == 0.5
    assert cumulative_traffic_fraction(FLAT_CURVE, 11 * 60) == 1.0
    assert cumulative_traffic_fraction([], 600) is None


def test_estimate_lost_sales_from_midday_sellout() -> None:
    estimate = estimate_lost_sales(
        FLAT_CURVE, prepared=20, last_sale=time(10, 0), close_time=time(11, 0)
    )
    assert estimate is not None
    # Sold out at the half-way mark -> full-day demand ~ double, ~20 units lost.
    assert estimate["estimated_full_day_demand"] == 40.0
    assert estimate["lost_units"] == 20.0
    assert estimate["remaining_minutes"] == 60
    assert estimate["sellout_clock"] == "10:00"


def test_estimate_requires_observed_last_sale() -> None:
    assert estimate_lost_sales(FLAT_CURVE, 20, None, time(11, 0)) is None


def test_estimate_skips_unreliably_early_sellout() -> None:
    # Sold out at 09:05, before ~10% of the day's traffic: too noisy to claim.
    assert estimate_lost_sales(FLAT_CURVE, 20, time(9, 5), time(11, 0)) is None
