"""Load observed synthetic parquet files into Postgres."""

from __future__ import annotations

import argparse
from pathlib import Path

from dialin.config import load_settings, mask_database_url
from dialin.loader import load_observed_directory


def main() -> None:
    """Parse CLI options and load observed data."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--observed-dir", type=Path, required=True)
    parser.add_argument("--mode", choices=["truncate-load", "upsert"], default="truncate-load")
    args = parser.parse_args()

    settings = load_settings()
    print(f"loading into {mask_database_url(settings.migration_database_url)}")
    load_observed_directory(settings.migration_database_url, args.observed_dir, mode=args.mode)
    print("load complete")


if __name__ == "__main__":
    main()
