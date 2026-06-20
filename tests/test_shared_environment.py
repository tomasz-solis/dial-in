"""Tests for the pooled environment layer and cold-start prior (PRD 10.8, 13)."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from dialin.engine import build_recommendations
from dialin.shared_environment import (
    InsufficientPoolError,
    cold_start_prior,
    fit_environment_layer,
)


def _pooled_features(
    *,
    cities: int = 3,
    days: int = 50,
    temp_beta: float = 0.02,
    rain_beta: float = -0.015,
    locations_per_cell: int = 3,
    seed: int = 11,
) -> pd.DataFrame:
    """Synthetic shared-layer aggregates with a known weather response."""

    rng = np.random.default_rng(seed)
    rows: list[dict[str, object]] = []
    for city_index in range(cities):
        level = 100.0 + 40.0 * city_index  # different café identity per city
        for _day in range(days):
            temp = float(rng.normal(18.0, 6.0))
            rain = float(max(0.0, rng.gamma(1.1, 2.0) - 1.0))
            lift = np.exp(temp_beta * (temp - 18.0) + rain_beta * rain)
            noise = float(rng.normal(1.0, 0.02))
            rows.append(
                {
                    "city": f"city_{city_index}",
                    "country": "ES",
                    "date": date(2026, 1, 1),
                    "avg_drinks_sold": level * lift * noise,
                    "avg_temp_actual": temp,
                    "avg_rain_actual": rain,
                    "contributing_location_days": locations_per_cell,
                }
            )
    return pd.DataFrame(rows)


def test_fit_recovers_weather_response_and_emits_only_parameters() -> None:
    layer = fit_environment_layer(_pooled_features(temp_beta=0.03, rain_beta=-0.02))
    # Warmer lifts traffic; rain suppresses it.
    assert layer.temp_elasticity > 0
    assert layer.rain_elasticity < 0
    assert layer.weather_multiplier(28.0, 0.0) > layer.weather_multiplier(10.0, 0.0)
    assert layer.weather_multiplier(18.0, 12.0) < layer.weather_multiplier(18.0, 0.0)
    # The emitted artifact is parameters only — no city/level/raw rows.
    params = layer.as_parameters()
    assert set(params) == {
        "temp_elasticity",
        "rain_elasticity",
        "reference_temp_c",
        "contributing_location_days",
        "distinct_segments",
        "fitted_at",
    }


def test_multiplier_is_clamped_to_sane_bounds() -> None:
    layer = fit_environment_layer(_pooled_features(temp_beta=0.5))
    assert 0.6 <= layer.weather_multiplier(45.0, 0.0) <= 1.6
    assert 0.6 <= layer.weather_multiplier(-20.0, 80.0) <= 1.6


def test_sparse_pool_is_refused() -> None:
    # One segment, and cells below the per-cell location floor: must refuse.
    sparse = _pooled_features(cities=1, days=20, locations_per_cell=1)
    with pytest.raises(InsufficientPoolError):
        fit_environment_layer(sparse)


def test_cold_start_prior_requires_opt_in() -> None:
    features = _pooled_features()
    with pytest.raises(InsufficientPoolError):
        cold_start_prior(features, country="ES", opt_in=False)


def test_cold_start_prior_is_wide_and_low_confidence() -> None:
    prior = cold_start_prior(_pooled_features(), country="ES", opt_in=True)
    assert prior.confidence == "Low"
    assert prior.lower_drinks < prior.baseline_drinks < prior.upper_drinks


def _engine_history() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    dates = pd.date_range("2026-02-01", periods=120, freq="D").date
    daily = pd.DataFrame(
        {
            "date": dates,
            "is_open": [True] * 120,
            "drinks_sold": [120] * 120,
            "input_source": ["confirmed"] * 120,
        }
    )
    category = pd.DataFrame(
        {
            "date": dates,
            "category": ["sweet"] * 120,
            "sold": [40] * 120,
            "prepared": [60] * 120,
            "sold_out": [False] * 120,
            "input_source": ["confirmed"] * 120,
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


def test_engine_records_environment_layer_when_supplied() -> None:
    daily, category, economics = _engine_history()
    layer = fit_environment_layer(_pooled_features())
    weather = pd.DataFrame(
        [
            {
                "date": date(2026, 6, 1),
                "temp_forecast": 28.0,
                "rain_forecast": 0.0,
                "condition": "sunny",
                "forecast_made_at": pd.Timestamp("2026-05-31 18:00", tz="UTC"),
            }
        ]
    )
    results = build_recommendations(
        account_id="acct_test",
        location_id="loc_test",
        target_date=date(2026, 6, 1),
        daily_metrics=daily,
        category_metrics=category,
        weather=weather,
        events=pd.DataFrame(),
        economics=economics,
        environment_layer=layer,
    )
    assert results[0].config_snapshot["environment_layer"] is not None
    assert "temp_elasticity" in results[0].config_snapshot["environment_layer"]
