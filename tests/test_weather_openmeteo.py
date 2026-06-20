"""Tests for the real Open-Meteo weather provider (PRD section 1.1)."""

from __future__ import annotations

import os
from datetime import date
from typing import Any

import pytest

from dialin.weather import OpenMeteoWeatherProvider, wmo_condition

SAMPLE_RESPONSE: dict[str, Any] = {
    "daily": {
        "time": ["2026-06-20", "2026-06-21"],
        "temperature_2m_mean": [24.5, 26.0],
        "temperature_2m_max": [29.0, 30.0],
        "temperature_2m_min": [20.0, 22.0],
        "precipitation_sum": [0.0, 3.4],
        "weather_code": [1, 61],
        "wind_speed_10m_max": [11.0, 14.0],
    }
}


def _provider(
    response: dict[str, Any], captured: list[str] | None = None
) -> OpenMeteoWeatherProvider:
    def fake_fetch(url: str) -> dict[str, Any]:
        if captured is not None:
            captured.append(url)
        return response

    return OpenMeteoWeatherProvider(41.0667, 1.06, timezone="Europe/Madrid", fetch_json=fake_fetch)


def test_maps_a_sunny_day() -> None:
    forecast = _provider(SAMPLE_RESPONSE).forecast_for(date(2026, 6, 20))
    assert forecast.source == "open_meteo"
    assert forecast.missing is False
    assert forecast.temp_forecast == 24.5
    assert forecast.rain_forecast == 0.0
    assert forecast.condition == "sunny"
    assert forecast.wind == 11.0


def test_maps_a_rainy_day() -> None:
    forecast = _provider(SAMPLE_RESPONSE).forecast_for(date(2026, 6, 21))
    assert forecast.condition == "rain"
    assert forecast.rain_forecast == 3.4
    assert forecast.temp_forecast == 26.0


def test_request_url_carries_coordinates_and_range() -> None:
    captured: list[str] = []
    _provider(SAMPLE_RESPONSE, captured).forecast_for(date(2026, 6, 20))
    assert len(captured) == 1
    url = captured[0]
    assert "latitude=41.0667" in url
    assert "longitude=1.06" in url
    assert "start_date=2026-06-20" in url
    assert "Europe%2FMadrid" in url


def test_falls_back_to_seasonal_normal_on_network_error() -> None:
    def boom(url: str) -> dict[str, Any]:
        raise OSError("network down")

    provider = OpenMeteoWeatherProvider(41.0667, 1.06, fetch_json=boom)
    forecast = provider.forecast_for(date(2026, 6, 20))
    assert forecast.missing is True
    assert forecast.source == "seasonal_normal"


def test_falls_back_on_malformed_provider_payload() -> None:
    provider = _provider({"daily": []})
    forecast = provider.forecast_for(date(2026, 6, 20))
    assert forecast.missing is True
    assert forecast.source == "seasonal_normal"


def test_missing_target_date_falls_back() -> None:
    forecast = _provider(SAMPLE_RESPONSE).forecast_for(date(2030, 1, 1))
    assert forecast.missing is True


def test_uses_minmax_when_mean_absent() -> None:
    response = {"daily": {**SAMPLE_RESPONSE["daily"], "temperature_2m_mean": [None, None]}}
    forecast = _provider(response).forecast_for(date(2026, 6, 20))
    assert forecast.temp_forecast == pytest.approx((29.0 + 20.0) / 2)


ARCHIVE_RESPONSE: dict[str, Any] = {
    "daily": {
        "time": ["2026-06-10", "2026-06-11"],
        "temperature_2m_mean": [22.0, 23.5],
        "precipitation_sum": [1.2, 0.0],
    }
}


def test_daily_actuals_maps_temp_and_rain() -> None:
    captured: list[str] = []
    provider = _provider(ARCHIVE_RESPONSE, captured)
    actuals = provider.daily_actuals(date(2026, 6, 10), date(2026, 6, 11))
    assert actuals[date(2026, 6, 10)] == (22.0, 1.2)
    assert actuals[date(2026, 6, 11)] == (23.5, 0.0)
    # Actuals hit the archive endpoint, not the forecast endpoint.
    assert "archive-api.open-meteo.com" in captured[0]


def test_wmo_condition_mapping() -> None:
    assert wmo_condition(0) == "sunny"
    assert wmo_condition(3) == "cloudy"
    assert wmo_condition(48) == "fog"
    assert wmo_condition(65) == "rain"
    assert wmo_condition(75) == "snow"
    assert wmo_condition(95) == "rain"


@pytest.mark.skipif(
    not os.environ.get("DIALIN_WEATHER_LIVE_TEST"),
    reason="set DIALIN_WEATHER_LIVE_TEST=1 to hit the real Open-Meteo API",
)
def test_live_open_meteo_returns_a_real_forecast() -> None:
    from datetime import UTC, datetime

    provider = OpenMeteoWeatherProvider(41.0667, 1.06, timezone="Europe/Madrid")
    forecast = provider.forecast_for(datetime.now(tz=UTC).date())
    assert forecast.source == "open_meteo"
    assert forecast.missing is False
    assert -30.0 < forecast.temp_forecast < 55.0
