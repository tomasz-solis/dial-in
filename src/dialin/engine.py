"""V1 rules engine for Dial In prep recommendations."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, cast

import pandas as pd

MODEL_VERSION = "v1-demo-rules"

# Demand uplift applied on sold-out days when fewer than 5 comparable uncensored
# days exist. This is an assumption, not an estimate: it invents a 15% tail on
# exactly the chronic-sellout days where the true ceiling was never observed
# (PRD section 12), so any recommendation that leaned on it is forced to Low
# confidence and flagged via TAIL_FALLBACK_RISK_FLAG.
FALLBACK_DEMAND_UPLIFT = 1.15
# Number of trailing calendar days in which a fallback-estimated row downgrades
# the category's confidence.
TAIL_FALLBACK_WINDOW_DAYS = 28
TAIL_FALLBACK_RISK_FLAG = "Still learning your ceiling"

# Negative Binomial dispersion controls. Larger dispersion means a tighter
# distribution (variance approaches the mean); smaller means wider ranges.
# SPARSE_HISTORY_DISPERSION applies with under 10 usable demand observations:
# moderately wide ranges because we know little. LOW_VARIANCE_DISPERSION applies
# when observed variance <= mean (the NB moment estimate is undefined there):
# near-Poisson, fairly tight. The floor stops a few wild days from exploding the
# range; the ceiling keeps the model from claiming near-certainty it has not
# earned. These are demo-tuned values, not fitted parameters; the PRD 11.1 path
# replaces them with per-bucket residual fits on real data.
SPARSE_HISTORY_DISPERSION = 20.0
LOW_VARIANCE_DISPERSION = 60.0
DISPERSION_FLOOR = 3.0
DISPERSION_CEILING = 80.0

# A category that frequently sells out has an under-observed upper tail, so a flat
# p90 band systematically under-covers true demand on high-demand days. Widen the
# upper quantile as the trailing censoring rate rises (PRD section 12: "widen,
# don't fake"), capped so the band never implies near-certainty. This only affects
# the displayed demand range, not the recommended prep (which uses the economics
# service quantile).
UPPER_TAIL_CENSOR_WIDENING = 0.3
MAX_UPPER_QUANTILE = 0.97


@dataclass(frozen=True)
class RecommendationResult:
    """One category-level prep recommendation."""

    account_id: str
    location_id: str
    date: date
    category: str
    recommended_prep: int
    demand_p50: int
    demand_p_lower: int
    demand_p_upper: int
    service_quantile: float
    confidence: str
    risk_flag: str
    top_drivers: list[dict[str, float | str]]
    model_version: str
    input_snapshot_id: str
    config_snapshot_id: str
    generated_at: datetime


def service_quantile(under_cost: float, over_cost: float) -> float:
    """Return the newsvendor operating quantile from under- and over-prep costs."""

    if under_cost <= 0:
        raise ValueError("under_cost must be positive")
    if over_cost <= 0:
        raise ValueError("over_cost must be positive")
    return under_cost / (under_cost + over_cost)


def build_recommendations(
    account_id: str,
    location_id: str,
    target_date: date,
    daily_metrics: pd.DataFrame,
    category_metrics: pd.DataFrame,
    weather: pd.DataFrame,
    events: pd.DataFrame,
    economics: pd.DataFrame,
) -> list[RecommendationResult]:
    """Build category recommendations from account-scoped observed history."""

    open_history = _open_history_before(daily_metrics, target_date)
    target_weather = _target_weather(weather, target_date)
    target_events = (
        events[pd.to_datetime(events["date"]).dt.date == target_date]
        if not events.empty
        else events
    )
    traffic_mean, traffic_drivers = _forecast_traffic(
        open_history, target_date, target_weather, target_events
    )
    results: list[RecommendationResult] = []

    for category in sorted(category_metrics["category"].dropna().unique()):
        category_history = _observed_category_history(category_metrics, str(category), target_date)
        if category_history.empty:
            continue
        economics_row = _economics_for_category(economics, category, target_date)
        corrected = decensored_demand_series(category_history, open_history)
        attach_rate = _trailing_attach_rate(corrected, open_history, target_date)
        demand_mean = max(traffic_mean * attach_rate, 0.5)
        dispersion = estimate_dispersion(
            corrected["estimated_demand"].tail(84).to_list(), demand_mean
        )
        censor_rate = float(category_history.tail(56)["sold_out"].mean())
        history_depth = int(category_history.shape[0])
        tail_fallback_recent = _tail_fallback_recent(corrected, target_date)
        confidence = _confidence(history_depth, censor_rate, target_weather)
        if tail_fallback_recent:
            confidence = "Low"
        lower_q, upper_q = (0.05, 0.95) if confidence == "Low" else (0.1, 0.9)
        upper_q = min(upper_q + censor_rate * UPPER_TAIL_CENSOR_WIDENING, MAX_UPPER_QUANTILE)
        demand_p_lower = negative_binomial_quantile(demand_mean, dispersion, lower_q)
        demand_p50 = negative_binomial_quantile(demand_mean, dispersion, 0.5)
        recommended_prep = negative_binomial_quantile(
            demand_mean,
            dispersion,
            float(economics_row["service_quantile"]),
        )
        demand_p_upper = negative_binomial_quantile(demand_mean, dispersion, upper_q)
        if tail_fallback_recent:
            risk_flag = TAIL_FALLBACK_RISK_FLAG
        else:
            risk_flag = _risk_flag(recommended_prep, demand_p_upper, censor_rate)
        drivers = _top_drivers(traffic_drivers, category, attach_rate, censor_rate)
        input_snapshot_id = stable_hash(
            {
                "target_date": target_date.isoformat(),
                "traffic_mean": round(traffic_mean, 4),
                "attach_rate": round(attach_rate, 6),
                "demand_mean": round(demand_mean, 4),
                "dispersion": round(dispersion, 4),
                "history_depth": history_depth,
                "censor_rate": round(censor_rate, 4),
                "tail_fallback_recent": tail_fallback_recent,
            }
        )
        config_snapshot_id = stable_hash(
            {
                "model_version": MODEL_VERSION,
                "economics": _json_ready(economics_row.to_dict()),
            }
        )
        results.append(
            RecommendationResult(
                account_id=account_id,
                location_id=location_id,
                date=target_date,
                category=str(category),
                recommended_prep=recommended_prep,
                demand_p50=demand_p50,
                demand_p_lower=demand_p_lower,
                demand_p_upper=demand_p_upper,
                service_quantile=float(economics_row["service_quantile"]),
                confidence=confidence,
                risk_flag=risk_flag,
                top_drivers=drivers,
                model_version=MODEL_VERSION,
                input_snapshot_id=input_snapshot_id,
                config_snapshot_id=config_snapshot_id,
                generated_at=datetime.now(tz=UTC),
            )
        )
    return results


def decensored_demand_series(
    category_history: pd.DataFrame, open_daily: pd.DataFrame
) -> pd.DataFrame:
    """Estimate demand on sold-out days using comparable uncensored days and drinks scale."""

    merged = category_history.merge(
        open_daily[["date", "drinks_sold"]],
        on="date",
        how="left",
    ).copy()
    merged["weekday"] = pd.to_datetime(merged["date"]).dt.weekday
    merged["estimated_demand"] = merged["sold"].astype(float)
    merged["tail_fallback"] = False

    for index, row in merged[merged["sold_out"] == True].iterrows():  # noqa: E712
        comparable = merged[
            (merged["sold_out"] == False)  # noqa: E712
            & (merged["weekday"] == row["weekday"])
            & (pd.to_datetime(merged["date"]) < pd.to_datetime(row["date"]))
        ].tail(12)
        if comparable.shape[0] >= 5 and comparable["drinks_sold"].median() > 0:
            scale = float(row["drinks_sold"]) / float(comparable["drinks_sold"].median())
            estimate = float(comparable["sold"].median()) * scale
        else:
            estimate = float(row["prepared"]) * FALLBACK_DEMAND_UPLIFT
            merged.loc[index, "tail_fallback"] = True
        merged.loc[index, "estimated_demand"] = max(float(row["prepared"]), estimate)
    return merged


def estimate_dispersion(values: list[float], fallback_mean: float) -> float:
    """Estimate Negative Binomial dispersion from recent demand variation."""

    clean = [float(value) for value in values if value >= 0]
    if len(clean) < 10:
        return SPARSE_HISTORY_DISPERSION
    mean = max(float(pd.Series(clean).mean()), fallback_mean, 0.5)
    variance = float(pd.Series(clean).var(ddof=1))
    if variance <= mean:
        return LOW_VARIANCE_DISPERSION
    return float(
        min(max(mean * mean / (variance - mean), DISPERSION_FLOOR), DISPERSION_CEILING)
    )


def negative_binomial_quantile(mean: float, dispersion: float, quantile: float) -> int:
    """Return an integer Negative Binomial quantile without a SciPy dependency."""

    if mean < 0:
        raise ValueError("mean must be non-negative")
    if dispersion <= 0:
        raise ValueError("dispersion must be positive")
    if not 0 < quantile < 1:
        raise ValueError("quantile must be between 0 and 1")

    mean = max(mean, 1e-9)
    probability = dispersion / (dispersion + mean)
    mass = probability**dispersion
    cumulative = mass
    value = 0
    variance = mean + mean * mean / dispersion
    limit = math.ceil(mean + 12 * math.sqrt(variance) + 100)
    while cumulative < quantile and value < limit:
        value += 1
        mass *= ((value - 1 + dispersion) / value) * (1 - probability)
        cumulative += mass
    return value


def stable_hash(payload: dict[str, Any]) -> str:
    """Hash recommendation inputs/configs in a stable JSON representation."""

    encoded = json.dumps(_json_ready(payload), sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def result_to_record(result: RecommendationResult) -> dict[str, Any]:
    """Convert a result dataclass to a database-ready record."""

    record = asdict(result)
    record["top_drivers"] = json.dumps(result.top_drivers)
    return record


def _open_history_before(daily_metrics: pd.DataFrame, target_date: date) -> pd.DataFrame:
    """Return open daily rows before the target date."""

    if daily_metrics.empty:
        return daily_metrics.copy()
    frame = daily_metrics.copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.date
    rows = frame[(frame["is_open"] == True) & (frame["date"] < target_date)].copy()  # noqa: E712
    if "input_source" in rows.columns:
        rows = rows[rows["input_source"] != "imputed"].copy()
    return rows


def _observed_category_history(
    category_metrics: pd.DataFrame,
    category: str,
    target_date: date,
) -> pd.DataFrame:
    """Return non-imputed category history before the target date."""

    frame = category_metrics[
        (category_metrics["category"] == category)
        & (pd.to_datetime(category_metrics["date"]).dt.date < target_date)
    ].copy()
    if "input_source" in frame.columns:
        frame = frame[frame["input_source"] != "imputed"].copy()
    return frame


def _target_weather(weather: pd.DataFrame, target_date: date) -> dict[str, Any]:
    """Return target-date weather or a seasonal-normal fallback."""

    if not weather.empty:
        frame = weather.copy()
        frame["date"] = pd.to_datetime(frame["date"]).dt.date
        rows = frame[frame["date"] == target_date]
        if not rows.empty:
            return cast(dict[str, Any], rows.iloc[0].to_dict())
    return {
        "temp_forecast": 18.0,
        "rain_forecast": 0.0,
        "condition": "seasonal normal",
        "missing": True,
    }


def _forecast_traffic(
    open_history: pd.DataFrame,
    target_date: date,
    target_weather: dict[str, Any],
    target_events: pd.DataFrame,
) -> tuple[float, dict[str, float]]:
    """Forecast drinks traffic from trailing same-weekday history and external lifts."""

    if open_history.empty:
        base = 100.0
    else:
        same_weekday = open_history[
            open_history["date"].map(lambda item: item.weekday()) == target_date.weekday()
        ]
        base_rows = same_weekday.tail(4) if same_weekday.shape[0] >= 2 else open_history.tail(28)
        base = float(base_rows["drinks_sold"].mean())
    temp = float(target_weather.get("temp_forecast", 18.0))
    rain = float(target_weather.get("rain_forecast", 0.0))
    weather_multiplier = max(
        0.78, 1 + min(max((temp - 18) * 0.007, -0.06), 0.08) - min(rain * 0.015, 0.16)
    )
    if target_events.empty:
        event_multiplier = 1.0
    else:
        event_multiplier = float((1 + target_events["impact_score"].astype(float)).prod())
    forecast = max(base * weather_multiplier * event_multiplier, 1.0)
    return forecast, {
        "weekday": base
        / max(float(open_history["drinks_sold"].mean()) if not open_history.empty else base, 1.0),
        "weather": weather_multiplier,
        "event": event_multiplier,
    }


def _economics_for_category(
    economics: pd.DataFrame, category: str, target_date: date
) -> pd.Series[Any]:
    """Return the effective economics row for a category and target date."""

    frame = economics[economics["category"] == category].copy()
    if frame.empty:
        raise ValueError(f"missing category economics for {category}")
    target_timestamp = pd.Timestamp(target_date)
    frame["effective_from"] = pd.to_datetime(frame["effective_from"])
    frame["effective_to"] = pd.to_datetime(frame["effective_to"])
    effective = frame[
        (frame["effective_from"] <= target_timestamp)
        & (frame["effective_to"].isna() | (frame["effective_to"] > target_timestamp))
    ]
    if effective.empty:
        raise ValueError(f"no effective category economics for {category} on {target_date}")
    return effective.sort_values("effective_from").iloc[-1]


def _trailing_attach_rate(
    corrected: pd.DataFrame,
    open_history: pd.DataFrame,
    target_date: date,
) -> float:
    """Estimate de-censored category attach rate over the trailing four weeks."""

    start = target_date - timedelta(days=28)
    recent = corrected[pd.to_datetime(corrected["date"]).dt.date >= start].copy()
    if recent.shape[0] < 8:
        recent = corrected.tail(56).copy()
    recent = recent.merge(
        open_history[["date", "drinks_sold"]], on="date", how="left", suffixes=("", "_daily")
    )
    drinks = recent["drinks_sold_daily"].fillna(recent["drinks_sold"]).clip(lower=1)
    attach = float(recent["estimated_demand"].sum() / drinks.sum())
    return float(min(max(attach, 0.03), 0.8))


def _tail_fallback_recent(corrected: pd.DataFrame, target_date: date) -> bool:
    """Return whether the fabricated-tail fallback fired in the trailing window."""

    if "tail_fallback" not in corrected.columns or corrected.empty:
        return False
    window_start = target_date - timedelta(days=TAIL_FALLBACK_WINDOW_DAYS)
    recent = corrected[pd.to_datetime(corrected["date"]).dt.date >= window_start]
    return bool(recent["tail_fallback"].any())


def _confidence(history_depth: int, censor_rate: float, target_weather: dict[str, Any]) -> str:
    """Convert data depth and input quality into an owner-facing confidence label."""

    if target_weather.get("missing") or history_depth < 40 or censor_rate > 0.38:
        return "Low"
    if history_depth < 90 or censor_rate > 0.25:
        return "Medium"
    return "High"


def _risk_flag(recommended_prep: int, demand_p_upper: int, censor_rate: float) -> str:
    """Return the concise risk label shown in the app."""

    if censor_rate > 0.38:
        return "Stockout learning needed"
    if demand_p_upper - recommended_prep > max(3, int(recommended_prep * 0.18)):
        return "High demand possible"
    return "Normal"


def _top_drivers(
    traffic_drivers: dict[str, float],
    category: str,
    attach_rate: float,
    censor_rate: float,
) -> list[dict[str, float | str]]:
    """Pick the three largest readable drivers for a recommendation."""

    candidates: list[dict[str, float | str]] = [
        {"name": "weekday pattern", "multiplier": round(float(traffic_drivers["weekday"]), 3)},
        {"name": "weather forecast", "multiplier": round(float(traffic_drivers["weather"]), 3)},
        {"name": "local events", "multiplier": round(float(traffic_drivers["event"]), 3)},
        {"name": f"{category} attach", "multiplier": round(1 + attach_rate, 3)},
        {"name": "sellout correction", "multiplier": round(1 + censor_rate, 3)},
    ]
    return sorted(candidates, key=_driver_distance, reverse=True)[:3]


def _driver_distance(driver: dict[str, float | str]) -> float:
    """Return how far a driver multiplier is from neutral."""

    multiplier = driver["multiplier"]
    if isinstance(multiplier, str):
        return abs(float(multiplier) - 1)
    return abs(multiplier - 1)


def _json_ready(value: Any) -> Any:
    """Convert pandas, dates, and dataclasses to stable JSON values."""

    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if isinstance(value, tuple):
        return [_json_ready(item) for item in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        try:
            return value.item()
        except ValueError:
            return str(value)
    return value
