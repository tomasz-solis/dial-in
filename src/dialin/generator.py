"""Synthetic café data generator for the Dial In demo."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

CATEGORIES = ("sweet", "savory")
DEFAULT_END_DATE = date(2026, 5, 30)


@dataclass(frozen=True)
class CafeConfig:
    """Configuration for one synthetic café profile."""

    account_id: str
    account_name: str
    location_id: str
    location_name: str
    timezone: str
    city: str
    country: str
    open_days: tuple[int, ...]
    base_drinks: float
    capacity_hint: int
    weekday_multipliers: tuple[float, float, float, float, float, float, float]
    sweet_attach: float
    savory_attach: float
    habit_factor: float
    weekend_leisure_bias: float


@dataclass(frozen=True)
class GeneratedDataset:
    """Container for observed and planted-truth synthetic tables."""

    observed: dict[str, pd.DataFrame]
    truth: dict[str, pd.DataFrame]
    run_config: dict[str, Any]


def default_cafes() -> tuple[CafeConfig, CafeConfig]:
    """Return the two single-location demo cafés used by the app."""

    return (
        CafeConfig(
            account_id="acct_fadri",
            account_name="Fadri (fictionalized)",
            location_id="loc_fadri_main",
            location_name="Fadri Café Demo",
            timezone="Europe/Madrid",
            city="Cambrils, Tarragona",
            country="ES",
            open_days=(1, 2, 3, 4, 5, 6),
            base_drinks=142,
            capacity_hint=245,
            weekday_multipliers=(0.0, 0.88, 0.94, 1.0, 1.08, 1.48, 1.62),
            sweet_attach=0.36,
            savory_attach=0.14,
            habit_factor=0.95,
            weekend_leisure_bias=1.18,
        ),
        CafeConfig(
            account_id="acct_dummy",
            account_name="Station House Demo",
            location_id="loc_dummy_main",
            location_name="Station House",
            timezone="Europe/Madrid",
            city="Valencia",
            country="ES",
            open_days=(0, 1, 2, 3, 4, 5),
            base_drinks=126,
            capacity_hint=205,
            weekday_multipliers=(1.18, 1.14, 1.1, 1.08, 1.0, 0.76, 0.0),
            sweet_attach=0.31,
            savory_attach=0.18,
            habit_factor=0.95,
            weekend_leisure_bias=0.92,
        ),
    )


def generate_synthetic_dataset(
    seed: int = 20260531,
    end_date: date = DEFAULT_END_DATE,
    months: int = 18,
) -> GeneratedDataset:
    """Generate observed and truth tables for the synthetic demo."""

    rng = np.random.default_rng(seed)
    start_date = end_date - timedelta(days=round(months * 30.5))
    dates = pd.date_range(start=start_date, end=end_date, freq="D").date

    accounts: list[dict[str, Any]] = []
    locations: list[dict[str, Any]] = []
    location_hours: list[dict[str, Any]] = []
    daily_metrics: list[dict[str, Any]] = []
    category_metrics: list[dict[str, Any]] = []
    weather_rows: list[dict[str, Any]] = []
    event_rows: list[dict[str, Any]] = []
    economics_rows: list[dict[str, Any]] = []
    traffic_truth: list[dict[str, Any]] = []
    category_truth: list[dict[str, Any]] = []

    for cafe in default_cafes():
        accounts.append(
            {
                "account_id": cafe.account_id,
                "name": cafe.account_name,
                "plan": "demo",
                "contributes_to_shared_layer": True,
                "cold_start_pool_opt_in": False,
                "pos_backfill_months": months,
                "created_at": _local_timestamp(dates[0], cafe.timezone, 8),
            }
        )
        locations.append(
            {
                "account_id": cafe.account_id,
                "location_id": cafe.location_id,
                "name": cafe.location_name,
                "timezone": cafe.timezone,
                "city": cafe.city,
                "country": cafe.country,
                "open_days": list(cafe.open_days),
                "service_capacity_hint": cafe.capacity_hint,
                "created_at": _local_timestamp(dates[0], cafe.timezone, 8),
            }
        )
        location_hours.extend(_location_hours_rows(cafe, dates[0]))
        economics_rows.extend(_economics_rows(cafe, dates[0]))
        sold_history: dict[str, list[tuple[date, int, int]]] = {
            category: [] for category in CATEGORIES
        }

        for current_date in dates:
            weekday = current_date.weekday()
            is_open = weekday in cafe.open_days
            weather = _weather_for_day(cafe, current_date, rng)
            weather_rows.append(weather)
            day_events = _events_for_day(cafe, current_date, rng)
            event_rows.extend(day_events)

            if not is_open:
                daily_metrics.append(
                    {
                        "account_id": cafe.account_id,
                        "location_id": cafe.location_id,
                        "date": current_date,
                        "timezone": cafe.timezone,
                        "is_open": False,
                        "drinks_sold": None,
                        "input_source": "confirmed",
                        "menu_version": "v1",
                        "recorded_at": _local_timestamp(current_date, cafe.timezone, 18),
                    }
                )
                traffic_truth.append(
                    {
                        "account_id": cafe.account_id,
                        "location_id": cafe.location_id,
                        "date": current_date,
                        "true_drinks": 0,
                        "throughput_limited": False,
                    }
                )
                continue

            event_multiplier = math.prod(1 + float(row["impact_score"]) for row in day_events)
            traffic_mean = (
                cafe.base_drinks
                * cafe.weekday_multipliers[weekday]
                * _season_multiplier(current_date, cafe.city)
                * _weather_multiplier(weather)
                * event_multiplier
                * _payday_multiplier(current_date)
                * _regime_drift(current_date, dates[0], dates[-1])
            )
            true_drinks = _negative_binomial(rng, traffic_mean, dispersion=28)
            capacity = round(cafe.capacity_hint * rng.normal(1.0, 0.035))
            observed_drinks = min(true_drinks, capacity)
            throughput_limited = true_drinks > capacity

            daily_metrics.append(
                {
                    "account_id": cafe.account_id,
                    "location_id": cafe.location_id,
                    "date": current_date,
                    "timezone": cafe.timezone,
                    "is_open": True,
                    "drinks_sold": int(observed_drinks),
                    "input_source": "confirmed",
                    "menu_version": "v1",
                    "recorded_at": _local_timestamp(current_date, cafe.timezone, 18),
                }
            )
            traffic_truth.append(
                {
                    "account_id": cafe.account_id,
                    "location_id": cafe.location_id,
                    "date": current_date,
                    "true_drinks": int(true_drinks),
                    "throughput_limited": bool(throughput_limited),
                }
            )

            for category in CATEGORIES:
                attach = cafe.sweet_attach if category == "sweet" else cafe.savory_attach
                category_adjustment = _category_adjustment(
                    category, weekday, cafe.weekend_leisure_bias
                )
                demand_mean = max(observed_drinks * attach * category_adjustment, 1.0)
                true_demand = _negative_binomial(rng, demand_mean, dispersion=18)
                prepared = _gut_prep_quantity(
                    rng=rng,
                    history=sold_history[category],
                    current_date=current_date,
                    fallback_mean=demand_mean,
                    habit_factor=cafe.habit_factor,
                )
                observed_sold = min(true_demand, prepared)
                sold_out = observed_sold >= max(prepared - 1, 0)
                salvage_share = 0.0 if category == "sweet" else 0.18
                waste_units = max(prepared - true_demand, 0) * (1 - salvage_share)
                lost_units = max(true_demand - prepared, 0)

                category_metrics.append(
                    {
                        "account_id": cafe.account_id,
                        "location_id": cafe.location_id,
                        "date": current_date,
                        "category": category,
                        "sold": int(observed_sold),
                        "prepared": int(prepared),
                        "sold_out": bool(sold_out),
                        "stockout_detected_by": "inferred_cap",
                        "time_last_sale": (
                            _sellout_time(current_date, cafe.timezone, rng) if sold_out else pd.NaT
                        ),
                        "salvage_share_observed": None,
                        "input_source": "confirmed",
                    }
                )
                category_truth.append(
                    {
                        "account_id": cafe.account_id,
                        "location_id": cafe.location_id,
                        "date": current_date,
                        "category": category,
                        "true_demand": int(true_demand),
                        "lost_units": int(lost_units),
                        "waste_units": float(round(waste_units, 3)),
                        "salvage_share": float(salvage_share),
                    }
                )
                sold_history[category].append((current_date, int(observed_sold), int(prepared)))

    observed = {
        "accounts": pd.DataFrame(accounts),
        "locations": pd.DataFrame(locations),
        "location_hours": pd.DataFrame(location_hours),
        "daily_metrics": pd.DataFrame(daily_metrics),
        "daily_category_metrics": pd.DataFrame(category_metrics),
        "weather": pd.DataFrame(weather_rows),
        "events": pd.DataFrame(event_rows),
        "category_economics": pd.DataFrame(economics_rows),
    }
    truth = {
        "traffic_truth": pd.DataFrame(traffic_truth),
        "category_demand_truth": pd.DataFrame(category_truth),
    }
    run_config = {
        "seed": seed,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "months": months,
        "cafes": [asdict(cafe) for cafe in default_cafes()],
    }
    return GeneratedDataset(observed=observed, truth=truth, run_config=run_config)


def write_dataset(dataset: GeneratedDataset, output_dir: Path) -> dict[str, str]:
    """Write observed/truth parquet files and return SHA-256 hashes."""

    observed_dir = output_dir / "observed"
    truth_dir = output_dir / "truth"
    observed_dir.mkdir(parents=True, exist_ok=True)
    truth_dir.mkdir(parents=True, exist_ok=True)

    hashes: dict[str, str] = {}
    for folder, tables in ((observed_dir, dataset.observed), (truth_dir, dataset.truth)):
        for name, frame in tables.items():
            path = folder / f"{name}.parquet"
            frame.to_parquet(path, index=False)
            hashes[str(path.relative_to(output_dir))] = _file_sha256(path)

    run_config = dict(dataset.run_config)
    run_config["file_hashes"] = hashes
    config_path = truth_dir / "run_config.json"
    config_path.write_text(json.dumps(run_config, indent=2, sort_keys=True), encoding="utf-8")
    hashes[str(config_path.relative_to(output_dir))] = _file_sha256(config_path)
    return hashes


def _economics_rows(cafe: CafeConfig, effective_from: date) -> list[dict[str, Any]]:
    """Build category economics rows for a demo café."""

    rows: list[dict[str, Any]] = []
    specs = {
        "sweet": {
            "retail_price": 3.5,
            "unit_cogs": 0.9,
            "salvage_share_default": 0.0,
            "attached_drink_margin": 1.5,
            "attach_and_balk_rate": 0.4,
        },
        "savory": {
            "retail_price": 5.2,
            "unit_cogs": 1.7,
            "salvage_share_default": 0.18,
            "attached_drink_margin": 1.5,
            "attach_and_balk_rate": 0.25,
        },
    }
    for category, values in specs.items():
        under_cost = (
            values["retail_price"]
            - values["unit_cogs"]
            + values["attach_and_balk_rate"] * values["attached_drink_margin"]
        )
        over_cost = values["unit_cogs"] * (1 - values["salvage_share_default"])
        service_quantile = under_cost / (under_cost + over_cost)
        rows.append(
            {
                "account_id": cafe.account_id,
                "location_id": cafe.location_id,
                "category": category,
                **values,
                "service_quantile": round(service_quantile, 4),
                "effective_from": effective_from,
                "effective_to": None,
                "values_source": "default",
            }
        )
    return rows


def _location_hours_rows(cafe: CafeConfig, effective_from: date) -> list[dict[str, Any]]:
    """Build effective-dated opening hours rows for a demo café."""

    rows: list[dict[str, Any]] = []
    for day_of_week in range(7):
        is_open = day_of_week in cafe.open_days
        rows.append(
            {
                "account_id": cafe.account_id,
                "location_id": cafe.location_id,
                "day_of_week": day_of_week,
                "is_open": is_open,
                "open_time": time(8, 0) if is_open else None,
                "close_time": time(16, 0) if is_open else None,
                "effective_from": effective_from,
                "effective_to": None,
                "source": "demo_seed",
                "created_at": _local_timestamp(effective_from, cafe.timezone, 8),
            }
        )
    return rows


def _weather_for_day(
    cafe: CafeConfig, current_date: date, rng: np.random.Generator
) -> dict[str, Any]:
    """Generate forecast and actual weather for a local business date."""

    day_of_year = current_date.timetuple().tm_yday
    city_offset = 1.5 if cafe.city == "Valencia" else 0.0
    seasonal_temp = 17 + city_offset + 8 * math.sin(2 * math.pi * (day_of_year - 95) / 365)
    temp_actual = seasonal_temp + rng.normal(0, 3.0)
    rainy_season = 1.0 + 0.5 * math.cos(2 * math.pi * (day_of_year - 290) / 365)
    rain_actual = max(0.0, rng.gamma(1.2, 2.2 * rainy_season) - 1.6)
    temp_forecast = temp_actual + rng.normal(0, 1.8)
    rain_forecast = max(0.0, rain_actual + rng.normal(0, 1.4))
    condition = "rain" if rain_actual > 4 else "cloudy" if rain_actual > 0.6 else "sunny"
    return {
        "account_id": cafe.account_id,
        "location_id": cafe.location_id,
        "date": current_date,
        "temp_forecast": round(float(temp_forecast), 2),
        "temp_actual": round(float(temp_actual), 2),
        "rain_forecast": round(float(rain_forecast), 2),
        "rain_actual": round(float(rain_actual), 2),
        "wind": round(float(max(1.0, rng.normal(10, 4))), 2),
        "condition": condition,
        "forecast_made_at": _local_timestamp(current_date - timedelta(days=1), cafe.timezone, 18),
        "actual_observed_at": _local_timestamp(current_date, cafe.timezone, 18),
    }


def _events_for_day(
    cafe: CafeConfig,
    current_date: date,
    rng: np.random.Generator,
) -> list[dict[str, Any]]:
    """Generate sparse local event rows for one café-day."""

    rows: list[dict[str, Any]] = []
    if cafe.account_id == "acct_fadri" and current_date.weekday() == 5:
        rows.append(
            _event_row(
                cafe, current_date, "Neighborhood market", "market", 0.16, "demo_seed", "High"
            )
        )
    if (
        cafe.account_id == "acct_fadri"
        and current_date.month in {4, 9}
        and current_date.day in {12, 13}
    ):
        rows.append(
            _event_row(cafe, current_date, "Food festival", "festival", 0.32, "demo_seed", "Medium")
        )
    if cafe.account_id == "acct_dummy" and current_date.weekday() == 2 and rng.random() < 0.16:
        rows.append(
            _event_row(
                cafe, current_date, "Office district promo", "workday", 0.08, "demo_seed", "Medium"
            )
        )
    if current_date.month == 3 and current_date.day == 17:
        rows.append(
            _event_row(cafe, current_date, "City marathon", "sport", 0.38, "demo_seed", "Medium")
        )
    return rows


def _event_row(
    cafe: CafeConfig,
    current_date: date,
    name: str,
    event_type: str,
    impact_score: float,
    source: str,
    confidence: str,
) -> dict[str, Any]:
    """Create one event row in the observed schema."""

    return {
        "account_id": cafe.account_id,
        "location_id": cafe.location_id,
        "date": current_date,
        "event_name": name,
        "event_type": event_type,
        "impact_score": impact_score,
        "source": source,
        "confidence": confidence,
    }


def _gut_prep_quantity(
    rng: np.random.Generator,
    history: list[tuple[date, int, int]],
    current_date: date,
    fallback_mean: float,
    habit_factor: float,
) -> int:
    """Simulate a conservative prep-by-gut policy keyed off censored sales."""

    same_weekday = [
        sold for day, sold, _prepared in history if day.weekday() == current_date.weekday()
    ]
    if len(same_weekday) >= 2:
        baseline = max(float(np.mean(same_weekday[-4:])), fallback_mean * 0.9)
    else:
        baseline = fallback_mean
    buffer = 1.9 * math.sqrt(max(baseline, 1.0))
    noise = rng.normal(1.0, 0.075)
    return max(1, round((baseline * habit_factor + buffer) * noise))


def _negative_binomial(rng: np.random.Generator, mean: float, dispersion: float) -> int:
    """Sample an overdispersed count with variance greater than its mean."""

    mean = max(float(mean), 0.1)
    dispersion = max(float(dispersion), 1.0)
    probability = dispersion / (dispersion + mean)
    return int(rng.negative_binomial(dispersion, probability))


def _season_multiplier(current_date: date, city: str) -> float:
    """Return a smooth seasonal multiplier with a summer tourism bump."""

    day_of_year = current_date.timetuple().tm_yday
    annual = 1.0 + 0.07 * math.sin(2 * math.pi * (day_of_year - 80) / 365)
    summer_bump = (
        1.1
        if city in {"Barcelona", "Cambrils, Tarragona", "Valencia"}
        and current_date.month in {6, 7, 8}
        else 1.0
    )
    return annual * summer_bump


def _weather_multiplier(weather: dict[str, Any]) -> float:
    """Convert weather into a traffic multiplier."""

    temp = float(weather["temp_actual"])
    rain = float(weather["rain_actual"])
    warm_lift = min(max((temp - 16) * 0.008, -0.08), 0.09)
    rain_drag = min(rain * 0.018, 0.18)
    return max(0.72, 1 + warm_lift - rain_drag)


def _category_adjustment(category: str, weekday: int, weekend_leisure_bias: float) -> float:
    """Return category-specific attach movement by weekday."""

    weekend = weekday >= 5
    if category == "sweet":
        return weekend_leisure_bias if weekend else 1.0
    return 0.9 if weekend else 1.08


def _payday_multiplier(current_date: date) -> float:
    """Inject a real-world signal the demo engine deliberately does not know."""

    return 1.06 if 25 <= current_date.day <= 31 else 1.0


def _regime_drift(current_date: date, start_date: date, end_date: date) -> float:
    """Inject slow demand drift so the rules engine cannot be perfect."""

    span = max((end_date - start_date).days, 1)
    progress = (current_date - start_date).days / span
    return 0.96 + 0.09 * progress


def _sellout_time(current_date: date, timezone: str, rng: np.random.Generator) -> pd.Timestamp:
    """Simulate the last sale time on a sellout day."""

    hour = int(np.clip(rng.normal(13.1, 1.4), 10, 16))
    minute = int(rng.integers(0, 60))
    return pd.Timestamp(datetime.combine(current_date, time(hour, minute)), tz=ZoneInfo(timezone))


def _local_timestamp(current_date: date, timezone: str, hour: int) -> pd.Timestamp:
    """Create a timezone-aware timestamp for a local business date."""

    return pd.Timestamp(datetime.combine(current_date, time(hour, 0)), tz=ZoneInfo(timezone))


def _file_sha256(path: Path) -> str:
    """Hash a generated artifact for reproducibility checks."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
