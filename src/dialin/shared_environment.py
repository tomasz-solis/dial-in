"""Pooled environment-response layer and cold-start prior (PRD sections 10.8, 13).

The serving path is strictly per-tenant (RLS). The *training* path is where the
PRD allows cross-account data — but only as **anonymised aggregates in, model
parameters out**, never raw rows. Postgres already enforces this: the
``shared_layer_features`` view aggregates open days by city/country/date across
accounts that opted in (``contributes_to_shared_layer``) and is readable by the
platform-admin role only, never a tenant role.

This module is the offline training job that consumes that view:

* :func:`fit_environment_layer` estimates generic weather elasticities (the only
  lasting network effect, PRD section 13) and emits an :class:`EnvironmentLayer`
  of **parameters only**. It refuses sparse segments (PRD assumption 9 / section
  10.8 "≥ N consenting accounts") so a near-unique café cannot leak through.
* :func:`cold_start_prior` returns a wide, Low-confidence baseline level for a
  brand-new café with no POS backfill, conditioned on country/footfall band and
  gated on opt-in (PRD section 13 cold-start path).

Nothing here returns another tenant's rows, counts, or name; a tenant benefits
solely as weights in the shared layer.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, cast

import numpy as np
import pandas as pd
from numpy.typing import NDArray

# Governance thresholds. A segment must pool enough distinct location-days and
# span enough cells before any parameter is fit, so the layer estimates physics,
# not one café's identity.
MIN_LOCATIONS_PER_CELL = 2
MIN_QUALIFYING_ROWS = 60
MIN_DISTINCT_SEGMENTS = 2

# Multiplier clamp so a noisy elasticity can never imply an extreme swing.
WEATHER_MULTIPLIER_FLOOR = 0.6
WEATHER_MULTIPLIER_CEILING = 1.6


class InsufficientPoolError(RuntimeError):
    """Raised when the consenting pool is too sparse to fit a shared layer safely."""


@dataclass(frozen=True)
class EnvironmentLayer:
    """Fitted, anonymised weather elasticities — parameters only, no raw rows."""

    temp_elasticity: float
    rain_elasticity: float
    reference_temp_c: float
    contributing_location_days: int
    distinct_segments: int
    fitted_at: datetime

    def weather_multiplier(self, temp_c: float, rain_mm: float) -> float:
        """Return the pooled weather lift for a temperature and rainfall."""

        log_lift = self.temp_elasticity * (temp_c - self.reference_temp_c)
        log_lift += self.rain_elasticity * rain_mm
        return float(
            min(max(math.exp(log_lift), WEATHER_MULTIPLIER_FLOOR), WEATHER_MULTIPLIER_CEILING)
        )

    def as_parameters(self) -> dict[str, Any]:
        """Return the emitted parameter set (what the job publishes)."""

        return {
            "temp_elasticity": round(self.temp_elasticity, 6),
            "rain_elasticity": round(self.rain_elasticity, 6),
            "reference_temp_c": round(self.reference_temp_c, 4),
            "contributing_location_days": self.contributing_location_days,
            "distinct_segments": self.distinct_segments,
            "fitted_at": self.fitted_at.isoformat(),
        }


@dataclass(frozen=True)
class ColdStartPrior:
    """A wide, Low-confidence starting baseline for a café with no own history."""

    segment: str
    baseline_drinks: float
    lower_drinks: float
    upper_drinks: float
    confidence: str = "Low"
    contributing_location_days: int = 0
    notes: list[str] = field(default_factory=list)


def _ols(design: NDArray[np.float64], target: NDArray[np.float64]) -> NDArray[np.float64]:
    """Least-squares solve with an lstsq fallback for near-singular designs."""

    gram = design.T @ design
    try:
        return cast(NDArray[np.float64], np.linalg.solve(gram, design.T @ target))
    except np.linalg.LinAlgError:
        return cast(NDArray[np.float64], np.linalg.lstsq(design, target, rcond=None)[0])


def _qualifying_rows(shared_features: pd.DataFrame) -> pd.DataFrame:
    """Keep only cells that pool enough location-days to be safe to learn from."""

    frame = shared_features.copy()
    required = {"city", "avg_drinks_sold", "avg_temp_actual", "contributing_location_days"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"shared features missing columns: {sorted(missing)}")
    frame = frame[frame["contributing_location_days"] >= MIN_LOCATIONS_PER_CELL]
    frame = frame.dropna(subset=["avg_drinks_sold", "avg_temp_actual"])
    frame = frame[frame["avg_drinks_sold"] > 0]
    return frame


def fit_environment_layer(shared_features: pd.DataFrame) -> EnvironmentLayer:
    """Fit pooled weather elasticities from the anonymised shared-layer view.

    ``shared_features`` is the output of the ``shared_layer_features`` view
    (city, country, date, avg_drinks_sold, avg_temp_actual, avg_rain_actual,
    contributing_location_days). Demand level is removed by normalising within
    each city segment, so only the weather *response* is estimated. Raises
    :class:`InsufficientPoolError` when the consenting pool is too sparse.
    """

    frame = _qualifying_rows(shared_features)
    if len(frame) < MIN_QUALIFYING_ROWS or frame["city"].nunique() < MIN_DISTINCT_SEGMENTS:
        raise InsufficientPoolError(
            "Not enough consenting, pooled location-days to fit a shared layer "
            f"({len(frame)} qualifying rows across {frame['city'].nunique()} segments; "
            f"need >= {MIN_QUALIFYING_ROWS} rows and >= {MIN_DISTINCT_SEGMENTS} segments)."
        )

    segment_mean = frame.groupby("city")["avg_drinks_sold"].transform("mean")
    normalized = np.log(frame["avg_drinks_sold"].to_numpy() / segment_mean.to_numpy())
    temp = frame["avg_temp_actual"].astype(float).to_numpy()
    reference_temp = float(np.mean(temp))
    rain = frame.get("avg_rain_actual")
    rain_values = (
        np.zeros(len(frame)) if rain is None else rain.astype(float).fillna(0.0).to_numpy()
    )
    design = np.column_stack(
        [np.ones(len(frame)), temp - reference_temp, rain_values]
    )
    coefficients = _ols(design, normalized)
    return EnvironmentLayer(
        temp_elasticity=float(coefficients[1]),
        rain_elasticity=float(coefficients[2]),
        reference_temp_c=reference_temp,
        contributing_location_days=int(frame["contributing_location_days"].sum()),
        distinct_segments=int(frame["city"].nunique()),
        fitted_at=datetime.now(tz=UTC),
    )


def cold_start_prior(
    shared_features: pd.DataFrame,
    *,
    country: str,
    footfall_band: tuple[float, float] | None = None,
    opt_in: bool,
    range_width: float = 0.45,
) -> ColdStartPrior:
    """Return a wide, Low-confidence baseline for a no-history café (opt-in only).

    The baseline is a pooled *level* — the one place the PRD permits cross-account
    level pooling — so it is gated on ``opt_in`` and on the segment having enough
    pooled location-days. The range is deliberately wide and confidence Low; it
    decays to nothing as the café's own data arrives.
    """

    notes: list[str] = []
    if not opt_in:
        raise InsufficientPoolError(
            "Cold-start level pooling is opt-in (cold_start_pool_opt_in); not enabled."
        )
    frame = _qualifying_rows(shared_features)
    if "country" in frame.columns:
        frame = frame[frame["country"] == country]
    if footfall_band is not None:
        low, high = footfall_band
        frame = frame[(frame["avg_drinks_sold"] >= low) & (frame["avg_drinks_sold"] <= high)]
    if frame.empty or int(frame["contributing_location_days"].sum()) < MIN_QUALIFYING_ROWS:
        raise InsufficientPoolError(
            f"Cold-start segment for {country!r} is too sparse to seed a prior safely."
        )
    baseline = float(frame["avg_drinks_sold"].median())
    notes.append("Pooled cold-start prior; widen range and keep confidence Low until own data.")
    return ColdStartPrior(
        segment=country,
        baseline_drinks=round(baseline, 1),
        lower_drinks=round(baseline * (1.0 - range_width), 1),
        upper_drinks=round(baseline * (1.0 + range_width), 1),
        contributing_location_days=int(frame["contributing_location_days"].sum()),
        notes=notes,
    )
