"""Tests for the weather provider seam and forecast-staleness handling."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pandas as pd
import pytest

from dialin.engine import build_recommendations
from dialin.weather import (
    STALE_FORECAST_AGE_HOURS,
    FrameWeatherProvider,
    forecast_age_hours,
    forecast_from_row,
    seasonal_normal_forecast,
)

TARGET = date(2026, 6, 1)


def _row(made_at: datetime | None) -> dict[str, object]:
    return {
        "date": TARGET,
        "temp_forecast": 21.5,
        "rain_forecast": 0.4,
        "condition": "sunny",
        "forecast_source": "open_meteo",
        "forecast_made_at": made_at,
    }


def test_fresh_forecast_is_not_stale() -> None:
    fresh = datetime.combine(TARGET, datetime.min.time(), tzinfo=UTC) - timedelta(hours=6)
    forecast = forecast_from_row(_row(fresh), TARGET)
    assert forecast.missing is False
    assert forecast.stale is False
    assert forecast.source == "open_meteo"
    assert forecast.age_hours is not None and 0 < forecast.age_hours < 24


def test_old_forecast_is_stale() -> None:
    old = datetime.combine(TARGET, datetime.min.time(), tzinfo=UTC) - timedelta(
        hours=STALE_FORECAST_AGE_HOURS + 24
    )
    forecast = forecast_from_row(_row(old), TARGET)
    assert forecast.stale is True
    assert forecast.missing is False


def test_missing_row_falls_back_to_seasonal_normal() -> None:
    forecast = forecast_from_row(None, TARGET)
    assert forecast == seasonal_normal_forecast()
    assert forecast.missing is True
    assert forecast.stale is False
    assert forecast.source == "seasonal_normal"


def test_forecast_age_hours_treats_naive_as_utc() -> None:
    naive = datetime.combine(TARGET, datetime.min.time()) - timedelta(hours=12)
    aware = naive.replace(tzinfo=UTC)
    assert forecast_age_hours(naive, TARGET) == pytest.approx(forecast_age_hours(aware, TARGET))
    assert forecast_age_hours(naive, TARGET) == pytest.approx(12.0)


def test_frame_provider_empty_and_missing_date_fall_back() -> None:
    assert FrameWeatherProvider(pd.DataFrame()).forecast_for(TARGET).missing is True
    other_day = pd.DataFrame([_row(datetime(2026, 1, 1, tzinfo=UTC)) | {"date": date(2026, 1, 1)}])
    assert FrameWeatherProvider(other_day).forecast_for(TARGET).missing is True


def test_frame_provider_carries_wind_through() -> None:
    row = _row(datetime(2026, 6, 1, tzinfo=UTC)) | {"wind": 12.5}
    assert forecast_from_row(row, TARGET).wind == 12.5


def _healthy_history() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """A long, non-censored single-category history (otherwise High confidence)."""

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
            "sold": [38 + (index % 5) for index in range(120)],
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


def _weather_frame(made_at: datetime) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "date": date(2026, 6, 1),
                "temp_forecast": 19.0,
                "rain_forecast": 0.0,
                "condition": "sunny",
                "forecast_made_at": made_at,
            }
        ]
    )


def test_stale_forecast_lowers_engine_confidence() -> None:
    """A healthy history is High confidence on a fresh forecast, Low on a stale one."""

    daily, category, economics = _healthy_history()
    target = date(2026, 6, 1)
    midnight = datetime.combine(target, datetime.min.time(), tzinfo=UTC)

    fresh = build_recommendations(
        account_id="acct_test",
        location_id="loc_test",
        target_date=target,
        daily_metrics=daily,
        category_metrics=category,
        weather=_weather_frame(midnight - timedelta(hours=6)),
        events=pd.DataFrame(),
        economics=economics,
    )
    stale = build_recommendations(
        account_id="acct_test",
        location_id="loc_test",
        target_date=target,
        daily_metrics=daily,
        category_metrics=category,
        weather=_weather_frame(midnight - timedelta(days=10)),
        events=pd.DataFrame(),
        economics=economics,
    )

    assert fresh[0].confidence != "Low"
    assert stale[0].confidence == "Low"
    assert stale[0].input_snapshot["target_weather"]["stale"] is True
