"""Generate the synthetic observed/truth data files for Dial In."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from dialin.generator import generate_synthetic_dataset, write_dataset


def main() -> None:
    """Parse CLI options and write synthetic data files."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=20260531)
    parser.add_argument("--output", type=Path, default=Path("data/generated"))
    parser.add_argument("--end-date", type=date.fromisoformat, default=date(2026, 5, 30))
    args = parser.parse_args()

    dataset = generate_synthetic_dataset(seed=args.seed, end_date=args.end_date)
    hashes = write_dataset(dataset, args.output)
    print(f"wrote {len(hashes)} generated artifacts to {args.output}")


if __name__ == "__main__":
    main()
