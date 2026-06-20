"""Offline training job for the pooled environment-response layer (PRD 10.8).

This is the *privileged* job the PRD describes: it runs with the platform-admin
connection (never a user session), reads the anonymised ``shared_layer_features``
view (aggregates only, opted-in accounts only), fits generic weather
elasticities, and emits **parameters only** as JSON. It never reads or prints a
tenant's raw rows, counts, or name.

On a sparse pool — like the two-account synthetic demo — it refuses to fit and
says so, which is the honest outcome: the demo has not trained a real shared
layer (Architecture "Known Limits").

Usage::

    MIGRATION_DATABASE_URL=postgresql://owner:...@host/dialin \\
        uv run python scripts/train_shared_environment.py
"""

from __future__ import annotations

import json
import sys

import pandas as pd

from dialin.config import load_settings, mask_database_url
from dialin.db import admin_connection, fetch_all
from dialin.shared_environment import InsufficientPoolError, fit_environment_layer


def load_shared_features(admin_url: str) -> pd.DataFrame:
    """Read the anonymised shared-layer aggregates via the platform-admin role."""

    with admin_connection(admin_url) as conn:
        rows = fetch_all(
            conn,
            """
            SELECT city, country, date,
                   avg_drinks_sold, avg_temp_actual, avg_rain_actual,
                   contributing_location_days
            FROM shared_layer_features
            """,
        )
    return pd.DataFrame(rows)


def main() -> None:
    """Fit and print the environment layer, or report an insufficient pool."""

    settings = load_settings()
    admin_url = settings.migration_database_url
    print(f"reading shared_layer_features from {mask_database_url(admin_url)}")
    features = load_shared_features(admin_url)
    try:
        layer = fit_environment_layer(features)
    except InsufficientPoolError as error:
        print(f"shared layer NOT fitted: {error}")
        print("This is expected on the synthetic demo (too few consenting accounts).")
        sys.exit(0)
    print("fitted environment layer parameters:")
    print(json.dumps(layer.as_parameters(), indent=2))


if __name__ == "__main__":
    main()
