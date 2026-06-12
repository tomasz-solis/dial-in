"""Tests for the V1 recommendation engine."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pandas as pd
import pytest

from dialin.engine import (
    FALLBACK_DEMAND_UPLIFT,
    TAIL_FALLBACK_RISK_FLAG,
    _observed_category_history,
    _open_history_before,
    build_recommendations,
    decensored_demand_series,
    negative_binomial_quantile,
    service_quantile,
    stable_hash,
)
from dialin.generator import generate_synthetic_dataset


def test_service_quantile_and_distribution_are_monotonic() -> None:
    """Higher under-prep cost and higher quantiles should increase prep."""

    assert service_quantile(4.0, 1.0) > service_quantile(2.0, 1.0)
    assert negative_binomial_quantile(30, 15, 0.8) > negative_binomial_quantile(30, 15, 0.5)


def test_decensoring_lifts_sold_out_days() -> None:
    """Sold-out rows should be lifted above observed sold when possible."""

    daily = pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=8, freq="7D").date,
            "is_open": [True] * 8,
            "drinks_sold": [100, 102, 98, 101, 140, 142, 141, 143],
        }
    )
    category = pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=8, freq="7D").date,
            "category": ["sweet"] * 8,
            "sold": [30, 31, 29, 30, 40, 40, 40, 40],
            "prepared": [36, 36, 36, 36, 40, 40, 40, 40],
            "sold_out": [False, False, False, False, True, True, True, True],
        }
    )

    corrected = decensored_demand_series(category, daily)

    sold_out_estimates = corrected[corrected["sold_out"] == True]["estimated_demand"]  # noqa: E712
    assert sold_out_estimates.min() > 40


def test_decensoring_marks_tail_fallback_when_comparables_are_thin() -> None:
    """The assumed-uplift path must be flagged, never silent."""

    daily = pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=6, freq="7D").date,
            "is_open": [True] * 6,
            "drinks_sold": [100, 102, 98, 140, 142, 141],
        }
    )
    category = pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=6, freq="7D").date,
            "category": ["sweet"] * 6,
            "sold": [30, 31, 29, 40, 40, 40],
            "prepared": [36, 36, 36, 40, 40, 40],
            "sold_out": [False, False, False, True, True, True],
        }
    )

    corrected = decensored_demand_series(category, daily)

    sold_out_rows = corrected[corrected["sold_out"] == True]  # noqa: E712
    assert sold_out_rows["tail_fallback"].all()
    assert not corrected[corrected["sold_out"] == False]["tail_fallback"].any()  # noqa: E712
    assert sold_out_rows["estimated_demand"].min() == pytest.approx(
        40 * FALLBACK_DEMAND_UPLIFT
    )


def test_recent_tail_fallback_forces_low_confidence() -> None:
    """A recommendation leaning on the assumed tail must say so."""

    dates = pd.date_range("2026-04-01", periods=30, freq="D").date
    daily = pd.DataFrame(
        {
            "date": dates,
            "is_open": [True] * 30,
            "drinks_sold": [100] * 30,
        }
    )
    category = pd.DataFrame(
        {
            "date": dates,
            "category": ["sweet"] * 30,
            "sold": [30] * 20 + [40] * 10,
            "prepared": [36] * 20 + [40] * 10,
            "sold_out": [False] * 20 + [True] * 10,
        }
    )
    economics = pd.DataFrame(
        {
            "category": ["sweet"],
            "service_quantile": [0.78],
            "effective_from": [date(2025, 1, 1)],
            "effective_to": [None],
        }
    )

    results = build_recommendations(
        account_id="acct_test",
        location_id="loc_test",
        target_date=date(2026, 5, 1),
        daily_metrics=daily,
        category_metrics=category,
        weather=pd.DataFrame(),
        events=pd.DataFrame(),
        economics=economics,
    )

    assert len(results) == 1
    assert results[0].confidence == "Low"
    assert results[0].risk_flag == TAIL_FALLBACK_RISK_FLAG


def test_training_history_excludes_imputed_daily_rows() -> None:
    """Skipped closeouts should not enter traffic history."""

    daily = pd.DataFrame(
        {
            "date": [date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3)],
            "is_open": [True, True, False],
            "drinks_sold": [100, None, None],
            "input_source": ["confirmed", "imputed", "confirmed"],
        }
    )

    history = _open_history_before(daily, date(2026, 1, 4))

    assert history["date"].to_list() == [date(2026, 1, 1)]


def test_training_history_excludes_imputed_category_rows() -> None:
    """Skipped closeouts should not enter category demand history."""

    category = pd.DataFrame(
        {
            "date": [date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3)],
            "category": ["sweet", "sweet", "savory"],
            "sold": [20, 1000, 12],
            "prepared": [24, 1000, 14],
            "sold_out": [False, True, False],
            "input_source": ["confirmed", "imputed", "confirmed"],
        }
    )

    history = _observed_category_history(category, "sweet", date(2026, 1, 4))

    assert history["date"].to_list() == [date(2026, 1, 1)]


def test_build_recommendations_from_generated_history() -> None:
    """Generated observed history should produce one recommendation per category."""

    dataset = generate_synthetic_dataset(seed=20260531)
    observed = dataset.observed
    account_id = "acct_fadri"
    target_date = date(2026, 5, 30)

    results = build_recommendations(
        account_id=account_id,
        location_id="loc_fadri_main",
        target_date=target_date,
        daily_metrics=observed["daily_metrics"][
            observed["daily_metrics"]["account_id"] == account_id
        ],
        category_metrics=observed["daily_category_metrics"][
            observed["daily_category_metrics"]["account_id"] == account_id
        ],
        weather=observed["weather"][observed["weather"]["account_id"] == account_id],
        events=observed["events"][observed["events"]["account_id"] == account_id],
        economics=observed["category_economics"][
            observed["category_economics"]["account_id"] == account_id
        ],
    )

    assert {result.category for result in results} == {"sweet", "savory"}
    assert all(result.recommended_prep >= result.demand_p50 for result in results)
    assert all(result.demand_p_upper >= result.demand_p_lower for result in results)


def test_stable_hash_accepts_postgres_decimal_values() -> None:
    """Snapshot hashing should handle Postgres numeric columns."""

    digest = stable_hash({"service_quantile": Decimal("0.7800"), "retail_price": Decimal("3.50")})

    assert len(digest) == 64
