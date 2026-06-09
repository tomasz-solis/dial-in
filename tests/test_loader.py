"""Tests for observed parquet loading helpers."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from dialin.generator import generate_synthetic_dataset, write_dataset
from dialin.loader import frame_to_rows, read_observed_frames


def test_read_observed_frames_adds_default_account_members(tmp_path: Path) -> None:
    """The loader should bind demo auth subjects when no members file exists."""

    dataset = generate_synthetic_dataset(seed=20260531)
    write_dataset(dataset, tmp_path)

    frames = read_observed_frames(tmp_path / "observed")

    assert "account_members" in frames
    assert set(frames["account_members"]["auth_subject"]) == {"demo", "dummy"}


def test_read_observed_frames_adds_default_location_hours(tmp_path: Path) -> None:
    """Older observed exports should still load without a location-hours file."""

    dataset = generate_synthetic_dataset(seed=20260531)
    write_dataset(dataset, tmp_path)
    (tmp_path / "observed" / "location_hours.parquet").unlink()

    frames = read_observed_frames(tmp_path / "observed")

    assert "location_hours" in frames
    assert set(frames["location_hours"]["day_of_week"]) == set(range(7))
    assert frames["location_hours"][frames["location_hours"]["is_open"] == True][  # noqa: E712
        "open_time"
    ].notna().all()


def test_loader_rejects_truth_leakage(tmp_path: Path) -> None:
    """A truth-only field in observed parquet should fail before DB writes."""

    dataset = generate_synthetic_dataset(seed=20260531)
    write_dataset(dataset, tmp_path)
    bad_path = tmp_path / "observed" / "daily_metrics.parquet"
    bad = pd.read_parquet(bad_path)
    bad["true_drinks"] = 123
    bad.to_parquet(bad_path, index=False)

    try:
        read_observed_frames(tmp_path / "observed")
    except ValueError as exc:
        assert "truth-only" in str(exc)
    else:
        raise AssertionError("truth leakage was accepted")


def test_frame_to_rows_converts_pandas_nulls() -> None:
    """Pandas null values should become plain None values for psycopg."""

    frame = pd.DataFrame({"a": [1], "b": [pd.NaT]})

    assert frame_to_rows(frame, ("a", "b")) == [(1, None)]
