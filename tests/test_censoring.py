"""Tests for the right-censored Tobit de-censoring estimator (PRD section 12)."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from dialin.censoring import (
    CENSORING_METHOD_TOBIT,
    tobit_decensored_demand,
)
from dialin.engine import build_recommendations


def _censored_history(
    *,
    n: int,
    prepared: int,
    true_mu_log: float,
    sigma_log: float,
    seed: int = 7,
) -> tuple[pd.DataFrame, pd.DataFrame, np.ndarray]:
    """Build a category history whose demand is right-censored at ``prepared``."""

    rng = np.random.default_rng(seed)
    dates = pd.date_range("2026-01-01", periods=n, freq="D").date
    true_demand = np.exp(rng.normal(true_mu_log, sigma_log, size=n))
    sold = np.minimum(true_demand, float(prepared))
    sold_out = true_demand >= float(prepared)
    daily = pd.DataFrame(
        {"date": dates, "is_open": [True] * n, "drinks_sold": np.full(n, 120.0)}
    )
    category = pd.DataFrame(
        {
            "date": dates,
            "category": ["sweet"] * n,
            "sold": np.round(sold).astype(int),
            "prepared": [prepared] * n,
            "sold_out": sold_out,
        }
    )
    return daily, category, true_demand


def test_tobit_recovers_latent_mean_better_than_naive_sold() -> None:
    """On censored data, Tobit's de-censored mean beats raw mean(sold)."""

    daily, category, true_demand = _censored_history(
        n=220, prepared=40, true_mu_log=float(np.log(46.0)), sigma_log=0.26
    )
    corrected = tobit_decensored_demand(category, daily)

    true_mean = float(true_demand.mean())
    naive_mean = float(category["sold"].mean())
    tobit_mean = float(corrected["estimated_demand"].mean())

    # There must be real censoring for this test to mean anything.
    assert bool(category["sold_out"].any())
    assert int((~category["sold_out"]).sum()) >= 8
    # De-censoring lifts the mean toward truth and beats the naive sold mean.
    assert tobit_mean > naive_mean
    assert abs(tobit_mean - true_mean) < abs(naive_mean - true_mean)


def test_tobit_estimate_never_below_prepared_on_sold_out_days() -> None:
    daily, category, _ = _censored_history(
        n=160, prepared=35, true_mu_log=float(np.log(42.0)), sigma_log=0.3
    )
    corrected = tobit_decensored_demand(category, daily)
    sold_out = corrected["sold_out"].astype(bool)
    assert (corrected.loc[sold_out, "estimated_demand"] >= 35).all()


def test_tobit_leaves_uncensored_history_untouched() -> None:
    """With no sellouts, estimated demand equals observed sold and nothing is faked."""

    daily, category, _ = _censored_history(
        n=120, prepared=200, true_mu_log=float(np.log(45.0)), sigma_log=0.2
    )
    assert not bool(category["sold_out"].any())
    corrected = tobit_decensored_demand(category, daily)
    assert (corrected["estimated_demand"] == category["sold"].astype(float)).all()
    assert not bool(corrected["tail_fallback"].any())


def test_tobit_falls_back_when_no_uncensored_anchor() -> None:
    """Almost-always sold out: bounded, flagged fallback rather than extrapolation."""

    daily, category, _ = _censored_history(
        n=60, prepared=20, true_mu_log=float(np.log(80.0)), sigma_log=0.15
    )
    corrected = tobit_decensored_demand(category, daily)
    sold_out = corrected["sold_out"].astype(bool)
    assert bool(corrected.loc[sold_out, "tail_fallback"].all())
    assert (corrected.loc[sold_out, "estimated_demand"] >= 20).all()


def test_engine_accepts_tobit_method_and_records_it() -> None:
    """The engine runs end-to-end with the Tobit method and audits the choice."""

    daily, category, _ = _censored_history(
        n=140, prepared=40, true_mu_log=float(np.log(46.0)), sigma_log=0.26
    )
    daily["input_source"] = "confirmed"
    category["input_source"] = "confirmed"
    economics = pd.DataFrame(
        {
            "category": ["sweet"],
            "service_quantile": [0.78],
            "values_source": ["owner_confirmed"],
            "effective_from": [date(2025, 1, 1)],
            "effective_to": [None],
        }
    )
    results = build_recommendations(
        account_id="acct_test",
        location_id="loc_test",
        target_date=date(2026, 5, 21),
        daily_metrics=daily,
        category_metrics=category,
        weather=pd.DataFrame(),
        events=pd.DataFrame(),
        economics=economics,
        censoring_method=CENSORING_METHOD_TOBIT,
    )
    assert len(results) == 1
    assert results[0].config_snapshot["censoring_method"] == CENSORING_METHOD_TOBIT
    assert results[0].recommended_prep > 0
