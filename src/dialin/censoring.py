"""Censoring-aware demand estimation for the real-data path (PRD section 12).

The demo de-censors sold-out days with a light comparable-day method
(``engine.decensored_demand_series``). The PRD's real path is a Tobit (Type-I,
right-censored) model on log-demand: sold-out days are right-censored (true demand
is at least ``prepared``), and plain regression on ``sold`` would just relearn the
café's own under-prep ceiling.

This module fits that model with numpy (no SciPy), by EM: impute the
truncated-normal moments of the censored days, then refit. A centred log-drinks
covariate lets busier censored days be lifted more. It returns the same frame as
the demo method (``estimated_demand`` + ``tail_fallback``) so the engine can swap
methods without other changes. Like the demo method, it stays advisory until a
café's model passes the section 6.4 ship-gate (PRD 11.1).
"""

from __future__ import annotations

import math
from typing import cast

import numpy as np
import pandas as pd
from numpy.typing import NDArray

FloatArray = NDArray[np.float64]

# Censoring-correction methods selectable by the engine.
CENSORING_METHOD_COMPARABLE = "comparable_day"  # demo default (engine module)
CENSORING_METHOD_TOBIT = "tobit"  # real-data path (this module)

# Mirrors engine.FALLBACK_DEMAND_UPLIFT; duplicated to keep this module
# import-cycle-free (the engine imports this module, not the reverse).
FALLBACK_DEMAND_UPLIFT = 1.15
# Below this many uncensored (leftover) days there is no reliable anchor for the
# latent demand level, so the Tobit fit is skipped for a bounded, flagged
# fallback instead of extrapolating a tail it never observed (PRD section 12).
MIN_UNCENSORED_FOR_TOBIT = 8

_SQRT2 = math.sqrt(2.0)
_INV_SQRT_2PI = 1.0 / math.sqrt(2.0 * math.pi)
_erf = np.vectorize(math.erf, otypes=[np.float64])


def _norm_pdf(z: FloatArray) -> FloatArray:
    """Standard normal density."""

    return _INV_SQRT_2PI * np.exp(-0.5 * z * z)


def _norm_cdf(z: FloatArray) -> FloatArray:
    """Standard normal CDF via the error function."""

    return cast(FloatArray, 0.5 * (1.0 + _erf(z / _SQRT2)))


def _mills_right(alpha: FloatArray) -> FloatArray:
    """Inverse Mills ratio for a right-censored normal: phi(a) / (1 - Phi(a))."""

    denom = np.maximum(_norm_cdf(-alpha), 1e-12)
    lam = _norm_pdf(alpha) / denom
    # As alpha -> +inf the ratio -> alpha; use that where the direct form blows up.
    asymptotic = alpha + 1.0 / np.maximum(np.abs(alpha), 1e-6)
    return cast(FloatArray, np.where(np.isfinite(lam) & (lam < 1e6), lam, asymptotic))


def _ols(design: FloatArray, target: FloatArray) -> FloatArray:
    """Solve least squares, falling back to lstsq for near-singular designs."""

    gram = design.T @ design
    try:
        return cast(FloatArray, np.linalg.solve(gram, design.T @ target))
    except np.linalg.LinAlgError:
        return cast(FloatArray, np.linalg.lstsq(design, target, rcond=None)[0])


def _fit_tobit(
    y: FloatArray,
    censor_at: FloatArray,
    design: FloatArray,
    censored: NDArray[np.bool_],
    *,
    max_iter: int = 200,
    tol: float = 1e-6,
) -> tuple[FloatArray, float]:
    """Fit a right-censored normal model by EM; return (coefficients, sigma)."""

    uncensored = ~censored
    anchor = design[uncensored] if uncensored.sum() >= design.shape[1] else design
    anchor_y = y[uncensored] if uncensored.sum() >= design.shape[1] else y
    beta = _ols(anchor, anchor_y)
    residual = anchor_y - anchor @ beta
    sigma = max(float(np.std(residual)) if residual.size else 0.5, 1e-3)

    for _ in range(max_iter):
        mu = design @ beta
        first_moment = y.copy()
        second_moment = y * y
        if censored.any():
            alpha = (censor_at[censored] - mu[censored]) / sigma
            lam = _mills_right(alpha)
            expected = mu[censored] + sigma * lam
            variance = np.maximum(sigma * sigma * (1.0 + alpha * lam - lam * lam), 0.0)
            first_moment[censored] = expected
            second_moment[censored] = variance + expected * expected
        beta_new = _ols(design, first_moment)
        mu_new = design @ beta_new
        sigma2 = float(np.mean(second_moment - 2.0 * mu_new * first_moment + mu_new * mu_new))
        sigma_new = math.sqrt(max(sigma2, 1e-6))
        converged = bool(np.max(np.abs(beta_new - beta)) < tol) and abs(sigma_new - sigma) < tol
        beta, sigma = beta_new, sigma_new
        if converged:
            break
    return beta, sigma


def tobit_decensored_demand(
    category_history: pd.DataFrame,
    open_daily: pd.DataFrame,
    *,
    min_uncensored: int = MIN_UNCENSORED_FOR_TOBIT,
) -> pd.DataFrame:
    """Estimate true demand on sold-out days with a right-censored Tobit model.

    Returns ``category_history`` joined to daily drinks with two added columns:
    ``estimated_demand`` (observed ``sold`` on uncensored days; the model's
    conditional demand estimate, never below ``prepared``, on censored days) and
    ``tail_fallback`` (True where a bounded fallback was used because the fit had
    no reliable anchor). Matches ``engine.decensored_demand_series`` so the engine
    can swap methods transparently.
    """

    merged = category_history.merge(
        open_daily[["date", "drinks_sold"]], on="date", how="left"
    ).copy()
    merged = merged.reset_index(drop=True)
    merged["estimated_demand"] = merged["sold"].astype(float)
    merged["tail_fallback"] = False

    censored = (merged["sold_out"] == True).to_numpy()  # noqa: E712
    if not censored.any():
        return merged

    prepared = merged["prepared"].astype(float).to_numpy()
    if int((~censored).sum()) < min_uncensored:
        # No reliable uncensored anchor: bounded, flagged fallback (PRD section 12
        # "widen, don't fake"), identical in spirit to the demo method's fallback.
        fallback = np.maximum(prepared * FALLBACK_DEMAND_UPLIFT, prepared)
        merged.loc[censored, "estimated_demand"] = fallback[censored]
        merged.loc[censored, "tail_fallback"] = True
        return merged

    sold = merged["sold"].astype(float).to_numpy()
    drinks_series = merged["drinks_sold"].astype(float)
    drinks = drinks_series.fillna(drinks_series.median()).to_numpy()
    y = np.log(np.maximum(sold, 0.5))
    censor_at = np.log(np.maximum(prepared, 0.5))

    log_drinks = np.log(np.maximum(drinks, 1.0))
    if float(np.nanstd(log_drinks)) > 1e-6:
        covariate = np.nan_to_num(log_drinks - float(np.nanmean(log_drinks)))
        design = np.column_stack([np.ones(len(y)), covariate])
    else:
        design = np.ones((len(y), 1))

    beta, sigma = _fit_tobit(y, censor_at, design, censored)
    mu = design @ beta
    alpha = (censor_at[censored] - mu[censored]) / sigma
    expected_log_demand = mu[censored] + sigma * _mills_right(alpha)
    estimate = np.maximum(np.exp(expected_log_demand), prepared[censored])
    merged.loc[censored, "estimated_demand"] = estimate
    return merged
