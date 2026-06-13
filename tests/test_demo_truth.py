"""Tests for the demo-only ground-truth demand loader."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from dialin.demo_truth import load_truth_demand


def _write_truth(path: Path) -> None:
    pd.DataFrame(
        {
            "account_id": ["acct_fadri", "acct_fadri", "acct_dummy"],
            "location_id": ["loc_fadri_main", "loc_fadri_main", "loc_dummy_main"],
            "date": ["2026-01-01", "2026-01-01", "2026-01-01"],
            "category": ["sweet", "savory", "sweet"],
            "true_demand": [60, 30, 10],
        }
    ).to_parquet(path)


def test_load_truth_demand_filters_to_tenant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only the session tenant's rows are returned, with the expected columns."""

    truth_file = tmp_path / "truth.parquet"
    _write_truth(truth_file)
    monkeypatch.setenv("DEMO_TRUTH_PATH", str(truth_file))

    frame = load_truth_demand("acct_fadri", "loc_fadri_main")

    assert frame is not None
    assert set(frame.columns) == {"date", "category", "true_demand"}
    assert len(frame) == 2  # the dummy account's row is excluded
    assert sorted(frame["category"]) == ["savory", "sweet"]


def test_load_truth_demand_missing_file_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Outside the demo (no fixture) the loader returns None instead of raising."""

    monkeypatch.setenv("DEMO_TRUTH_PATH", str(tmp_path / "does_not_exist.parquet"))
    assert load_truth_demand("acct_fadri", "loc_fadri_main") is None
