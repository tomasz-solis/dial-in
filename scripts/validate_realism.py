"""Run the synthetic data realism and contract gates."""

from __future__ import annotations

import argparse
from pathlib import Path

from dialin.validation import validate_generated_dataset


def main() -> None:
    """Validate generated data and exit non-zero on failure."""

    parser = argparse.ArgumentParser()
    parser.add_argument("base_dir", type=Path)
    args = parser.parse_args()

    result = validate_generated_dataset(args.base_dir)
    for name, value in sorted(result.metrics.items()):
        print(f"{name}: {value:.3f}")
    if not result.ok:
        for error in result.errors:
            print(f"ERROR: {error}")
        raise SystemExit(1)
    print("validation passed")


if __name__ == "__main__":
    main()
