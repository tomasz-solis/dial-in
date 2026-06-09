"""Tests for synthetic generation and realism gates."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from dialin.generator import generate_synthetic_dataset, write_dataset
from dialin.validation import ensure_no_truth_columns, validate_generated_dataset


def test_generated_dataset_passes_realism_gate(tmp_path: Path) -> None:
    """Generated demo data should satisfy the observed/truth contract."""

    dataset = generate_synthetic_dataset(seed=20260531)
    write_dataset(dataset, tmp_path)

    result = validate_generated_dataset(tmp_path)

    assert result.ok, result.errors
    assert 0.08 <= result.metrics["any_category_sellout_rate"] <= 0.42
    assert 0.03 <= result.metrics["waste_share_of_prepared"] <= 0.24


def test_generator_is_reproducible_for_same_seed() -> None:
    """The same seed should produce the same observed daily rows."""

    first = generate_synthetic_dataset(seed=123)
    second = generate_synthetic_dataset(seed=123)

    pd.testing.assert_frame_equal(first.observed["daily_metrics"], second.observed["daily_metrics"])
    pd.testing.assert_frame_equal(
        first.observed["daily_category_metrics"],
        second.observed["daily_category_metrics"],
    )
    pd.testing.assert_frame_equal(
        first.observed["location_hours"],
        second.observed["location_hours"],
    )


def test_generator_writes_location_hours() -> None:
    """Synthetic observed data should include effective-dated opening hours."""

    dataset = generate_synthetic_dataset(seed=20260531)
    hours = dataset.observed["location_hours"]

    assert {"acct_fadri", "acct_dummy"} == set(hours["account_id"])
    assert set(hours["day_of_week"]) == set(range(7))
    assert hours[hours["is_open"] == True]["open_time"].notna().all()  # noqa: E712


def test_fadri_demo_location_uses_cambrils_area() -> None:
    """The Fadri demo seed should use the real operating area."""

    dataset = generate_synthetic_dataset(seed=20260531)
    locations = dataset.observed["locations"]
    fadri = locations[locations["location_id"] == "loc_fadri_main"].iloc[0]

    assert fadri["city"] == "Cambrils, Tarragona"


def test_truth_columns_are_rejected() -> None:
    """Observed loaders must reject planted-demand columns."""

    frame = pd.DataFrame({"account_id": ["acct"], "true_demand": [10]})

    try:
        ensure_no_truth_columns(frame, "bad_table")
    except ValueError as exc:
        assert "truth-only" in str(exc)
    else:
        raise AssertionError("truth-only column was accepted")
