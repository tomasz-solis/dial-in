"""Tests for the weather-sync helpers and the scheduled-refresh account scope."""

from __future__ import annotations

from datetime import date
from typing import Any, cast

import pytest

from dialin.weather_sync import (
    _UPDATE_ACTUAL,
    _UPSERT_FORECAST,
    backfill_actuals,
    default_coordinates,
)
from scripts import scheduled_refresh


def test_default_coordinates_for_known_demo_location() -> None:
    coords = default_coordinates("acct_fadri", "loc_fadri_main")
    assert coords is not None
    latitude, longitude, timezone = coords
    assert (round(latitude, 3), round(longitude, 3)) == (41.067, 1.06)
    assert timezone == "Europe/Madrid"


def test_default_coordinates_unknown_location_is_none() -> None:
    assert default_coordinates("acct_unknown", "loc_unknown") is None


def test_real_forecast_write_clears_synthetic_actuals_and_records_source() -> None:
    assert "'open_meteo'" in _UPSERT_FORECAST
    assert "forecast_source = EXCLUDED.forecast_source" in _UPSERT_FORECAST
    assert "temp_actual = NULL" in _UPSERT_FORECAST
    assert "rain_actual = NULL" in _UPSERT_FORECAST
    assert "actual_observed_at = NULL" in _UPSERT_FORECAST
    assert "forecast_source = 'open_meteo'" in _UPDATE_ACTUAL


def test_active_accounts_without_admin_covers_demo_only() -> None:
    demo = scheduled_refresh.demo_account_ids()
    accounts, found_extra = scheduled_refresh.active_account_ids(demo, admin_url=None)
    assert set(accounts) == demo
    assert found_extra is False


def test_active_accounts_folds_in_discovered_extras(monkeypatch: pytest.MonkeyPatch) -> None:
    demo = scheduled_refresh.demo_account_ids()
    monkeypatch.setattr(
        scheduled_refresh,
        "_discover_account_ids",
        lambda _url: [*sorted(demo), "acct_new_cafe"],
    )
    accounts, found_extra = scheduled_refresh.active_account_ids(demo, admin_url="postgresql://x")
    assert "acct_new_cafe" in accounts
    assert set(demo).issubset(accounts)
    assert found_extra is True


class _FakeCursor:
    def __init__(self, rows: list[dict[str, Any]] | None = None, rowcount: int = 0) -> None:
        self._rows = rows or []
        self.rowcount = rowcount

    def fetchall(self) -> list[dict[str, Any]]:
        return self._rows

    def fetchone(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None


class _FakeConn:
    """Minimal connection: answers the missing-dates SELECT and records UPDATEs."""

    def __init__(self, missing: list[date]) -> None:
        self._missing = missing
        self.updated_dates: list[date] = []

    def execute(self, query: str, params: Any = None) -> _FakeCursor:
        if "UPDATE weather" in query:
            self.updated_dates.append(params["date"])
            return _FakeCursor(rowcount=1)
        if "FROM weather" in query:
            return _FakeCursor(rows=[{"date": day} for day in self._missing])
        return _FakeCursor()


class _FakeProvider:
    def __init__(self, actuals: dict[date, tuple[float | None, float | None]]) -> None:
        self._actuals = actuals

    def daily_actuals(
        self, start: date, end: date
    ) -> dict[date, tuple[float | None, float | None]]:
        return self._actuals


def test_backfill_actuals_fills_only_missing_dates_with_data() -> None:
    missing = [date(2026, 6, 10), date(2026, 6, 11), date(2026, 6, 12)]
    conn = _FakeConn(missing)
    provider = _FakeProvider(
        {
            date(2026, 6, 9): (20.0, 0.0),   # not in the missing set -> ignored
            date(2026, 6, 10): (21.0, 1.0),  # fills
            date(2026, 6, 11): (22.0, 0.0),  # fills
            date(2026, 6, 12): (None, None),  # too recent for the archive -> skipped
        }
    )
    filled = backfill_actuals(
        cast(Any, conn),
        cast(Any, provider),
        "acct_fadri",
        "loc_fadri_main",
        today=date(2026, 6, 13),
        max_lookback_days=60,
    )
    assert filled == 2
    assert conn.updated_dates == [date(2026, 6, 10), date(2026, 6, 11)]
