"""Validation gates for generated Dial In demo data."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

TRUTH_ONLY_COLUMNS = {"true_drinks", "true_demand", "lost_units", "waste_units", "salvage_share"}


@dataclass(frozen=True)
class ValidationResult:
    """A validation report with errors and summary metrics."""

    errors: list[str]
    metrics: dict[str, float]

    @property
    def ok(self) -> bool:
        """Return true when no validation errors were found."""

        return not self.errors


def validate_generated_dataset(base_dir: Path) -> ValidationResult:
    """Validate observed/truth separation, schema invariants, and realism bands."""

    observed_dir = base_dir / "observed"
    truth_dir = base_dir / "truth"
    errors: list[str] = []
    metrics: dict[str, float] = {}

    observed = _read_parquet_dir(observed_dir)
    truth = _read_parquet_dir(truth_dir)

    required_observed = {
        "accounts",
        "locations",
        "location_hours",
        "daily_metrics",
        "daily_category_metrics",
        "weather",
        "events",
        "category_economics",
    }
    missing = required_observed - set(observed)
    if missing:
        errors.append(f"missing observed tables: {sorted(missing)}")

    for name, frame in observed.items():
        leaked = TRUTH_ONLY_COLUMNS.intersection(frame.columns)
        if leaked:
            errors.append(f"{name} contains truth-only columns: {sorted(leaked)}")

    if "location_hours" in observed:
        _check_location_hours(observed["location_hours"], errors)

    if "daily_category_metrics" in observed:
        category = observed["daily_category_metrics"]
        bad_counts = category[category["sold"] > category["prepared"]]
        if not bad_counts.empty:
            errors.append(f"{len(bad_counts)} category rows have sold > prepared")
        bad_sold_out = category[
            category["sold_out"] != (category["sold"] >= category["prepared"] - 1)
        ]
        if not bad_sold_out.empty:
            errors.append(f"{len(bad_sold_out)} category rows have inconsistent sold_out flags")

    if {"daily_metrics", "daily_category_metrics"}.issubset(observed):
        daily = observed["daily_metrics"]
        category = observed["daily_category_metrics"]
        closed = daily[daily["is_open"] == False][["account_id", "location_id", "date"]]  # noqa: E712
        closed_keys = set(map(tuple, closed.to_numpy()))
        category_keys = set(map(tuple, category[["account_id", "location_id", "date"]].to_numpy()))
        if closed_keys.intersection(category_keys):
            errors.append("closed days have category demand rows")

        open_daily = daily[daily["is_open"] == True]  # noqa: E712
        merged = category.merge(
            open_daily[["account_id", "location_id", "date", "drinks_sold"]],
            on=["account_id", "location_id", "date"],
            how="left",
        )
        _add_observed_metrics(metrics, merged)

    if {"category_demand_truth"}.issubset(truth) and "daily_category_metrics" in observed:
        _add_truth_metrics(
            metrics, observed["daily_category_metrics"], truth["category_demand_truth"]
        )

    _check_realism(metrics, errors)
    return ValidationResult(errors=errors, metrics=metrics)


def ensure_no_truth_columns(frame: pd.DataFrame, table_name: str) -> None:
    """Raise if an observed frame contains planted-truth fields."""

    leaked = TRUTH_ONLY_COLUMNS.intersection(frame.columns)
    if leaked:
        raise ValueError(f"{table_name} contains truth-only columns: {sorted(leaked)}")


def _read_parquet_dir(path: Path) -> dict[str, pd.DataFrame]:
    """Read every parquet table from a directory."""

    if not path.exists():
        return {}
    return {file.stem: pd.read_parquet(file) for file in sorted(path.glob("*.parquet"))}


def _check_location_hours(hours: pd.DataFrame, errors: list[str]) -> None:
    """Check the generated opening-hours contract."""

    bad_weekdays = hours[~hours["day_of_week"].between(0, 6)]
    if not bad_weekdays.empty:
        errors.append(f"{len(bad_weekdays)} location_hours rows have invalid weekdays")

    open_rows = hours[hours["is_open"] == True]  # noqa: E712
    missing_times = open_rows[open_rows["open_time"].isna() | open_rows["close_time"].isna()]
    if not missing_times.empty:
        errors.append(f"{len(missing_times)} open location_hours rows are missing times")

    closed_rows = hours[hours["is_open"] == False]  # noqa: E712
    closed_with_times = closed_rows[
        closed_rows["open_time"].notna() | closed_rows["close_time"].notna()
    ]
    if not closed_with_times.empty:
        errors.append(f"{len(closed_with_times)} closed location_hours rows contain times")


def _add_observed_metrics(metrics: dict[str, float], merged: pd.DataFrame) -> None:
    """Add observed-only realism metrics to a report."""

    for category in ("sweet", "savory"):
        rows = merged[merged["category"] == category]
        if rows.empty:
            continue
        drinks = rows["drinks_sold"].clip(lower=1)
        metrics[f"{category}_attach_observed"] = float((rows["sold"] / drinks).mean())
        metrics[f"{category}_sellout_rate"] = float(rows["sold_out"].mean())
    any_sellout = merged.groupby(["account_id", "location_id", "date"])["sold_out"].max()
    metrics["any_category_sellout_rate"] = float(any_sellout.mean())


def _add_truth_metrics(
    metrics: dict[str, float],
    observed_category: pd.DataFrame,
    truth_category: pd.DataFrame,
) -> None:
    """Add truth-backed realism metrics that never enter the app database."""

    joined = observed_category.merge(
        truth_category,
        on=["account_id", "location_id", "date", "category"],
        how="inner",
    )
    prepared = joined["prepared"].clip(lower=1)
    metrics["waste_share_of_prepared"] = float((joined["waste_units"] / prepared).mean())


def _check_realism(metrics: dict[str, float], errors: list[str]) -> None:
    """Check broad café realism bands without pretending they are Fadri facts."""

    bands = {
        "sweet_attach_observed": (0.22, 0.5),
        "savory_attach_observed": (0.07, 0.28),
        "any_category_sellout_rate": (0.08, 0.42),
        "waste_share_of_prepared": (0.03, 0.24),
    }
    for metric, (low, high) in bands.items():
        value = metrics.get(metric)
        if value is None:
            continue
        if not low <= value <= high:
            errors.append(f"{metric}={value:.3f} outside realism band [{low:.2f}, {high:.2f}]")
