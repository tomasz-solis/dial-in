"""SKU-level readiness (PRD section 15 Phase 8).

The storage grain is account x location x date x category and the engine never
hardcodes ``sweet``/``savory`` -- it iterates whatever categories the data
contains. So moving from two categories to individual SKUs is a data/config
change, not an engine rewrite. These tests prove the engine produces a correct,
independently-priced recommendation per arbitrary SKU.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from dialin.engine import build_recommendations

SKUS = ["croissant", "focaccia", "vegan_cookie", "spinach_roll"]
SERVICE_QUANTILES = {
    "croissant": 0.82,
    "focaccia": 0.74,
    "vegan_cookie": 0.6,
    "spinach_roll": 0.78,
}


def _sku_history() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    dates = pd.date_range("2026-02-01", periods=100, freq="D").date
    daily = pd.DataFrame(
        {
            "date": dates,
            "is_open": [True] * 100,
            "drinks_sold": [130] * 100,
            "input_source": ["confirmed"] * 100,
        }
    )
    category_frames = []
    economics_rows = []
    for index, sku in enumerate(SKUS):
        base_sold = 14 + index * 4
        category_frames.append(
            pd.DataFrame(
                {
                    "date": dates,
                    "category": [sku] * 100,
                    "sold": [base_sold + (day % 3) for day in range(100)],
                    "prepared": [base_sold + 12] * 100,
                    "sold_out": [False] * 100,
                    "input_source": ["confirmed"] * 100,
                }
            )
        )
        economics_rows.append(
            {
                "category": sku,
                "service_quantile": SERVICE_QUANTILES[sku],
                "values_source": "owner_confirmed",
                "effective_from": date(2025, 1, 1),
                "effective_to": None,
            }
        )
    category = pd.concat(category_frames, ignore_index=True)
    economics = pd.DataFrame(economics_rows)
    return daily, category, economics


def test_engine_produces_one_recommendation_per_sku() -> None:
    daily, category, economics = _sku_history()
    results = build_recommendations(
        account_id="acct_sku",
        location_id="loc_sku",
        target_date=date(2026, 5, 12),
        daily_metrics=daily,
        category_metrics=category,
        weather=pd.DataFrame(),
        events=pd.DataFrame(),
        economics=economics,
    )
    assert {result.category for result in results} == set(SKUS)
    # Each SKU is priced at its own service quantile, not a shared default.
    by_category = {result.category: result for result in results}
    for sku, quantile in SERVICE_QUANTILES.items():
        assert by_category[sku].service_quantile == quantile
        assert by_category[sku].recommended_prep > 0
