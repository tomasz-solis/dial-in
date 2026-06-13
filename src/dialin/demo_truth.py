"""Demo-only access to synthetic ground-truth demand.

Truth is the answer key for the synthetic demo and deliberately does **not** live
in the tenant database (production has no truth, and the app's low-privilege role
must never read it as if it were observed data). It is a file fixture, read only
when present, and always surfaced in the UI as "synthetic ground truth (demo)".
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

DEFAULT_TRUTH_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "generated" / "truth"
    / "category_demand_truth.parquet"
)


def truth_path() -> Path:
    """Return the configured truth-demand parquet path."""

    override = os.environ.get("DEMO_TRUTH_PATH")
    return Path(override) if override else DEFAULT_TRUTH_PATH


def load_truth_demand(account_id: str, location_id: str) -> pd.DataFrame | None:
    """Return date/category/true_demand for one tenant, or None when unavailable.

    Returns None (not an error) when the fixture is absent, so the app simply
    omits the ground-truth panel outside the synthetic demo.
    """

    path = truth_path()
    if not path.exists():
        return None
    frame = pd.read_parquet(path)
    required = {"account_id", "location_id", "date", "category", "true_demand"}
    if not required.issubset(frame.columns):
        return None
    scoped = frame[
        (frame["account_id"] == account_id) & (frame["location_id"] == location_id)
    ].copy()
    if scoped.empty:
        return None
    scoped["date"] = pd.to_datetime(scoped["date"])
    return scoped[["date", "category", "true_demand"]].reset_index(drop=True)
