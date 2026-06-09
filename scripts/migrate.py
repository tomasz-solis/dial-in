"""Apply Dial In database migrations to local Postgres or Neon."""

from __future__ import annotations

import argparse
from pathlib import Path

from dialin.config import load_settings, mask_database_url
from dialin.db import admin_connection


def migration_files() -> list[Path]:
    """Return migration files in deterministic order."""

    return sorted(Path("migrations").glob("*.sql"))


def apply_migrations(database_url: str) -> None:
    """Run every SQL migration in one transaction."""

    files = migration_files()
    if not files:
        raise RuntimeError("No migrations found.")

    with admin_connection(database_url) as conn:
        for path in files:
            sql = path.read_text(encoding="utf-8")
            conn.execute(sql)
            print(f"applied {path}")


def main() -> None:
    """Parse CLI options and apply migrations."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--target", choices=["local", "neon"], default="local")
    args = parser.parse_args()

    settings = load_settings()
    print(f"target={args.target} database={mask_database_url(settings.migration_database_url)}")
    apply_migrations(settings.migration_database_url)


if __name__ == "__main__":
    main()
