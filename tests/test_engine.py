"""Tests for the V1 recommendation engine."""

from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pandas as pd
import pytest

from dialin.engine import (
    FALLBACK_DEMAND_UPLIFT,
    PROBE_MAX_EXTRA_UNITS,
    PROBE_RISK_FLAG,
    TAIL_FALLBACK_RISK_FLAG,
    _observed_category_history,
    _open_history_before,
    _probe_decision,
    build_recommendations,
    decensored_demand_series,
    negative_binomial_quantile,
    result_to_record,
    service_quantile,
    stable_hash,
)
from dialin.generator import generate_synthetic_dataset


def _chronic_sellout_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return a long, mostly sold-out single-category history for probe tests."""

    dates = pd.date_range("2026-01-01", periods=140, freq="D").date
    daily = pd.DataFrame(
        {
            "date": dates,
            "is_open": [True] * 140,
            "drinks_sold": [120] * 140,
            "input_source": ["confirmed"] * 140,
        }
    )
    # Sold out on ~80% of days: a chronically censored category (censor_rate > 0.38).
    sold_out = [(index % 5) != 0 for index in range(140)]
    category = pd.DataFrame(
        {
            "date": dates,
            "category": ["sweet"] * 140,
            "sold": [40 if out else 30 for out in sold_out],
            "prepared": [40 if out else 36 for out in sold_out],
            "sold_out": sold_out,
            "input_source": ["confirmed"] * 140,
        }
    )
    economics = pd.DataFrame(
        {
            "category": ["sweet"],
            "service_quantile": [0.78],
            "values_source": ["owner_confirmed"],
            "effective_from": [date(2025, 1, 1)],
            "effective_to": [None],
        }
    )
    return daily, category, economics


def _first_probe_result(probe_opt_in: bool) -> tuple[date, list[Any]]:
    """Build recommendations across candidate dates and return the first probe day."""

    daily, category, economics = _chronic_sellout_inputs()
    last_result: list[Any] = []
    for offset in range(40):
        target_date = date(2026, 5, 21) + timedelta(days=offset)
        results = build_recommendations(
            account_id="acct_probe",
            location_id="loc_probe",
            target_date=target_date,
            daily_metrics=daily,
            category_metrics=category,
            weather=pd.DataFrame(),
            events=pd.DataFrame(),
            economics=economics,
            probe_opt_in=probe_opt_in,
        )
        last_result = results
        if any(result.probe_active for result in results):
            return target_date, results
    return date(2026, 5, 21), last_result


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


def test_training_history_keeps_current_menu_version_only() -> None:
    """A menu-version change should down-weight pre-change demand history."""

    daily = pd.DataFrame(
        {
            "date": [date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3)],
            "is_open": [True, True, True],
            "drinks_sold": [100, 120, 140],
            "input_source": ["confirmed", "confirmed", "confirmed"],
            "menu_version": ["v1", "v1", "summer"],
        }
    )

    history = _open_history_before(daily, date(2026, 1, 4))

    assert history["date"].to_list() == [date(2026, 1, 3)]


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


def test_recommendation_snapshots_are_replayable_and_hashed() -> None:
    """A generated recommendation should retain the inputs and config needed to explain it."""

    dataset = generate_synthetic_dataset(seed=20260531)
    observed = dataset.observed
    account_id = "acct_fadri"
    target_date = date(2026, 5, 30)

    result = build_recommendations(
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
    )[0]

    assert result.input_snapshot_id == stable_hash(result.input_snapshot)
    assert result.config_snapshot_id == stable_hash(result.config_snapshot)
    assert result.input_snapshot["target_date"] == target_date.isoformat()
    assert result.input_snapshot["history_depth"] > 0
    assert {"traffic_drivers", "attach_rate", "censor_rate", "range_quantiles"}.issubset(
        result.input_snapshot
    )
    assert result.config_snapshot["economics"]["values_source"] == "default"
    assert "upper_tail_censor_widening" in result.config_snapshot["constants"]
    record = result_to_record(result)
    assert json.loads(record["input_snapshot"])["category"] == result.category
    assert json.loads(record["config_snapshot"])["model_version"] == result.model_version


def test_stable_hash_accepts_postgres_decimal_values() -> None:
    """Snapshot hashing should handle Postgres numeric columns."""

    digest = stable_hash({"service_quantile": Decimal("0.7800"), "retail_price": Decimal("3.50")})

    assert len(digest) == 64


def test_probe_is_off_by_default() -> None:
    """A chronically sold-out category must not probe unless the account opted in."""

    _, results = _first_probe_result(probe_opt_in=False)

    assert results
    assert not any(result.probe_active for result in results)
    assert all(result.probe_extra_units == 0 for result in results)


def test_probe_fires_on_chronic_low_risk_day_and_is_bounded() -> None:
    """An opted-in chronic-sellout category should probe with bounded, disclosed extra."""

    target_date, results = _first_probe_result(probe_opt_in=True)

    probed = [result for result in results if result.probe_active]
    assert probed, f"expected a probe by {target_date}"
    result = probed[0]
    assert 0 < result.probe_extra_units <= PROBE_MAX_EXTRA_UNITS
    assert result.risk_flag == PROBE_RISK_FLAG
    assert result.input_snapshot["probe"] == {
        "active": True,
        "extra_units": result.probe_extra_units,
    }
    # The probe lifts prep above the owner's q* quantity by exactly the recorded extra.
    assert result.recommended_prep >= result.demand_p50


def test_probe_skips_when_a_known_event_elevates_the_day() -> None:
    """The probe must not add waste on days that already look high-demand."""

    daily, category, economics = _chronic_sellout_inputs()
    events = pd.DataFrame(
        {
            "date": [date(2026, 5, 23)],
            "event_name": ["street market"],
            "impact_score": [0.3],
        }
    )
    active, extra = _probe_decision(
        probe_opt_in=True,
        account_id="acct_probe",
        location_id="loc_probe",
        category="sweet",
        target_date=date(2026, 5, 23),
        censor_rate=0.8,
        traffic_drivers={"weekday": 1.0, "weather": 1.0, "event": 1.3},
        demand_mean=45.0,
        dispersion=20.0,
        recommended_prep=44,
    )

    assert active is False
    assert extra == 0
    del daily, category, economics, events


def test_probe_skips_low_censoring_categories() -> None:
    """A category that rarely sells out has an observed tail and needs no probe."""

    active, extra = _probe_decision(
        probe_opt_in=True,
        account_id="acct_probe",
        location_id="loc_probe",
        category="sweet",
        target_date=date(2026, 5, 23),
        censor_rate=0.1,
        traffic_drivers={"weekday": 1.0, "weather": 1.0, "event": 1.0},
        demand_mean=45.0,
        dispersion=20.0,
        recommended_prep=44,
    )

    assert active is False
    assert extra == 0
