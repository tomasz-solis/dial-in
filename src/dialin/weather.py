"""Weather provider seam, real Open-Meteo provider, and forecast staleness.

The #1 production to-do (PRD section 1.1, README) was replacing synthetic weather
with a real forecast + historical-actuals provider, "with forecast age and
fallback state shown" and "a seasonal-normal fallback that lowers confidence".
This module is both the seam and the real provider:

* ``WeatherForecast`` — a resolved target-date forecast carrying provenance
  (``source``), freshness (``stale``/``age_hours``), wind, and a ``missing`` flag.
* ``FrameWeatherProvider`` — resolves a forecast from the stored ``weather``
  table. The same path serves the synthetic generator's historical rows and the
  real forecasts written by ``scripts/fetch_weather.py``, so staleness/confidence
  handling is identical regardless of source.
* ``OpenMeteoWeatherProvider`` — the **real** provider: it calls the Open-Meteo
  API (free, no API key) for a location's coordinates, returning daily forecasts
  (``daily_forecasts``/``forecast_for``) and historical reanalysis proxies from the ERA5
  archive (``daily_actuals``). Network/parse failures degrade to seasonal normal.
* ``seasonal_normal_forecast`` — the low-confidence fallback used when no
  forecast row or API result exists for the target date.

A forecast is *stale* when it was made more than ``STALE_FORECAST_AGE_HOURS``
before the start of the target business day. The engine treats stale and missing
forecasts the same way: confidence drops to Low, which in turn widens the demand
range (PRD section 11.4 "widen, don't fake") rather than trusting an old number.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from typing import Any, Protocol, cast, runtime_checkable

import pandas as pd

# A next-day forecast is normally produced the evening before service (~6-18h
# ahead). Beyond this age the held forecast is treated as stale.
STALE_FORECAST_AGE_HOURS = 48.0

SEASONAL_NORMAL_TEMP_C = 18.0
SEASONAL_NORMAL_RAIN_MM = 0.0
SEASONAL_NORMAL_CONDITION = "seasonal normal"


@dataclass(frozen=True)
class WeatherForecast:
    """A resolved target-date forecast with provenance and freshness."""

    temp_forecast: float
    rain_forecast: float
    condition: str
    forecast_made_at: datetime | None
    source: str
    missing: bool
    stale: bool
    age_hours: float | None
    wind: float | None = None

    def as_engine_inputs(self) -> dict[str, Any]:
        """Return the dict the rules engine and context cards read.

        Keeps the legacy keys (``temp_forecast``, ``rain_forecast``,
        ``condition``, ``forecast_made_at``, ``missing``) so existing callers are
        unchanged, and adds ``source``, ``stale``, and ``forecast_age_hours`` so
        freshness is auditable in the recommendation input snapshot and visible
        in the UI.
        """

        return {
            "temp_forecast": self.temp_forecast,
            "rain_forecast": self.rain_forecast,
            "condition": self.condition,
            "forecast_made_at": self.forecast_made_at,
            "source": self.source,
            "missing": self.missing,
            "stale": self.stale,
            "forecast_age_hours": self.age_hours,
            "wind": self.wind,
        }


def seasonal_normal_forecast() -> WeatherForecast:
    """Return the low-confidence seasonal-normal fallback (no forecast available)."""

    return WeatherForecast(
        temp_forecast=SEASONAL_NORMAL_TEMP_C,
        rain_forecast=SEASONAL_NORMAL_RAIN_MM,
        condition=SEASONAL_NORMAL_CONDITION,
        forecast_made_at=None,
        source="seasonal_normal",
        missing=True,
        stale=False,
        age_hours=None,
    )


def forecast_age_hours(forecast_made_at: datetime, target_date: date) -> float:
    """Hours between when a forecast was made and the start of the target day.

    Positive means the forecast predates the target day (the normal case). The
    reference is midnight at the start of the target business day in UTC; naive
    timestamps are assumed UTC.
    """

    made = forecast_made_at if forecast_made_at.tzinfo else forecast_made_at.replace(tzinfo=UTC)
    reference = datetime.combine(target_date, time(0, 0), tzinfo=UTC)
    return (reference - made.astimezone(UTC)).total_seconds() / 3600.0


def forecast_from_row(
    row: dict[str, Any] | None,
    target_date: date,
    *,
    stale_after_hours: float = STALE_FORECAST_AGE_HOURS,
) -> WeatherForecast:
    """Build a forecast from one stored weather row, or the seasonal fallback."""

    if not row:
        return seasonal_normal_forecast()
    made_raw = row.get("forecast_made_at")
    made_dt: datetime | None = None
    if made_raw is not None and not pd.isna(made_raw):
        made_dt = pd.to_datetime(made_raw).to_pydatetime()
    age = forecast_age_hours(made_dt, target_date) if made_dt is not None else None
    stale = age is not None and age > stale_after_hours
    wind_raw = row.get("wind")
    return WeatherForecast(
        temp_forecast=float(row.get("temp_forecast", SEASONAL_NORMAL_TEMP_C)),
        rain_forecast=float(row.get("rain_forecast", SEASONAL_NORMAL_RAIN_MM)),
        condition=str(row.get("condition", SEASONAL_NORMAL_CONDITION)),
        forecast_made_at=made_dt,
        source=str(row.get("forecast_source") or "legacy"),
        missing=False,
        stale=stale,
        age_hours=round(age, 2) if age is not None else None,
        wind=None if wind_raw is None or pd.isna(wind_raw) else float(wind_raw),
    )


@runtime_checkable
class WeatherProvider(Protocol):
    """Resolve the forecast for a target business date."""

    def forecast_for(self, target_date: date) -> WeatherForecast: ...


@dataclass
class FrameWeatherProvider:
    """``WeatherProvider`` backed by the stored ``weather`` table.

    The frame already holds ``temp_forecast``/``rain_forecast``/``condition`` and
    the ``forecast_made_at`` timestamp, whether seeded synthetically today or
    written by a real feed later. A missing target-date row falls back to
    seasonal normal, so the engine never invents a confident number it does not
    have.
    """

    weather: pd.DataFrame
    stale_after_hours: float = STALE_FORECAST_AGE_HOURS

    def forecast_for(self, target_date: date) -> WeatherForecast:
        """Resolve the target-date forecast, computing freshness, or fall back."""

        if self.weather is None or self.weather.empty:
            return seasonal_normal_forecast()
        frame = self.weather.copy()
        frame["date"] = pd.to_datetime(frame["date"]).dt.date
        rows = frame[frame["date"] == target_date]
        if rows.empty:
            return seasonal_normal_forecast()
        return forecast_from_row(
            rows.iloc[0].to_dict(), target_date, stale_after_hours=self.stale_after_hours
        )


OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
# Historical reanalysis (ERA5). Used to backfill an outcome proxy once a forecast
# date has passed, so forecast-vs-actual error can be measured (PRD section 10.2).
OPEN_METEO_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

# Daily fields requested from Open-Meteo. temperature_2m_mean is the headline
# temp; max/min are a fallback if mean is unavailable for a day.
_DAILY_VARIABLES = (
    "temperature_2m_mean",
    "temperature_2m_max",
    "temperature_2m_min",
    "precipitation_sum",
    "weather_code",
    "wind_speed_10m_max",
)
_ACTUAL_VARIABLES = ("temperature_2m_mean", "precipitation_sum")

FetchJson = Callable[[str], dict[str, Any]]


def wmo_condition(code: int) -> str:
    """Map a WMO weather code to the app's condition vocabulary."""

    if code in (0, 1):
        return "sunny"
    if code in (45, 48):
        return "fog"
    if 71 <= code <= 77 or code in (85, 86):
        return "snow"
    if (51 <= code <= 67) or (80 <= code <= 82) or (95 <= code <= 99):
        return "rain"
    return "cloudy"


def _http_get_json(url: str, *, timeout: float = 10.0) -> dict[str, Any]:
    """GET a URL and parse JSON, using only the standard library."""

    request = urllib.request.Request(url, headers={"User-Agent": "dial-in/0.1 (+weather)"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = response.read()
    return cast(dict[str, Any], json.loads(payload))


def _safe_index(values: Any, index: int) -> float | None:
    """Return ``values[index]`` as a float when present and not null."""

    if not isinstance(values, list) or index >= len(values):
        return None
    value = values[index]
    return None if value is None else float(value)


class OpenMeteoWeatherProvider:
    """Real weather provider backed by the Open-Meteo API (PRD section 1.1).

    Open-Meteo is free and needs no API key. This fetches the daily forecast for
    a location's coordinates and maps it onto :class:`WeatherForecast`, with
    ``forecast_made_at`` set to the fetch time so the existing staleness handling
    applies. Network or parse failures degrade to the seasonal-normal fallback
    (lower confidence) rather than raising, matching the PRD's "fallback to
    seasonal normal, show Low confidence" requirement. ``fetch_json`` is
    injectable so the mapping can be tested without network access.
    """

    def __init__(
        self,
        latitude: float,
        longitude: float,
        *,
        timezone: str = "auto",
        forecast_url: str = OPEN_METEO_FORECAST_URL,
        archive_url: str = OPEN_METEO_ARCHIVE_URL,
        fetch_json: FetchJson = _http_get_json,
        stale_after_hours: float = STALE_FORECAST_AGE_HOURS,
    ) -> None:
        self.latitude = latitude
        self.longitude = longitude
        self.timezone = timezone
        self.forecast_url = forecast_url
        self.archive_url = archive_url
        self.fetch_json = fetch_json
        self.stale_after_hours = stale_after_hours

    def _url(self, base: str, start_date: date, end_date: date, variables: tuple[str, ...]) -> str:
        params = urllib.parse.urlencode(
            {
                "latitude": self.latitude,
                "longitude": self.longitude,
                "daily": ",".join(variables),
                "timezone": self.timezone,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
            }
        )
        return f"{base}?{params}"

    def daily_forecasts(self, start_date: date, end_date: date) -> dict[date, WeatherForecast]:
        """Fetch and map the daily forecast for an inclusive date range."""

        payload = self.fetch_json(
            self._url(self.forecast_url, start_date, end_date, _DAILY_VARIABLES)
        )
        daily = payload.get("daily") or {}
        times = daily.get("time") or []
        made_at = datetime.now(tz=UTC)
        forecasts: dict[date, WeatherForecast] = {}
        for index, day_text in enumerate(times):
            day = date.fromisoformat(str(day_text))
            temp = _safe_index(daily.get("temperature_2m_mean"), index)
            if temp is None:
                tmax = _safe_index(daily.get("temperature_2m_max"), index)
                tmin = _safe_index(daily.get("temperature_2m_min"), index)
                temp = (tmax + tmin) / 2 if tmax is not None and tmin is not None else None
            code = _safe_index(daily.get("weather_code"), index)
            age = forecast_age_hours(made_at, day)
            forecasts[day] = WeatherForecast(
                temp_forecast=SEASONAL_NORMAL_TEMP_C if temp is None else float(temp),
                rain_forecast=_safe_index(daily.get("precipitation_sum"), index) or 0.0,
                condition=SEASONAL_NORMAL_CONDITION if code is None else wmo_condition(int(code)),
                forecast_made_at=made_at,
                source="open_meteo",
                missing=False,
                stale=age > self.stale_after_hours,
                age_hours=round(age, 2),
                wind=_safe_index(daily.get("wind_speed_10m_max"), index),
            )
        return forecasts

    def forecast_for(self, target_date: date) -> WeatherForecast:
        """Return the real forecast for one date, or seasonal normal on failure."""

        try:
            forecasts = self.daily_forecasts(target_date, target_date)
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return seasonal_normal_forecast()
        return forecasts.get(target_date, seasonal_normal_forecast())

    def daily_actuals(
        self, start_date: date, end_date: date
    ) -> dict[date, tuple[float | None, float | None]]:
        """Fetch reanalysis (temp_actual, rain_actual) proxies from the ERA5 archive.

        Used to backfill what actually happened once a forecast date has passed,
        so forecast error becomes a feature (PRD section 10.2). Recent days may
        not be in the archive yet and are simply absent from the result.
        """

        payload = self.fetch_json(
            self._url(self.archive_url, start_date, end_date, _ACTUAL_VARIABLES)
        )
        daily = payload.get("daily") or {}
        times = daily.get("time") or []
        actuals: dict[date, tuple[float | None, float | None]] = {}
        for index, day_text in enumerate(times):
            day = date.fromisoformat(str(day_text))
            actuals[day] = (
                _safe_index(daily.get("temperature_2m_mean"), index),
                _safe_index(daily.get("precipitation_sum"), index),
            )
        return actuals
