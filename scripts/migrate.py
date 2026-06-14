"""Apply Dial In database migrations to local Postgres or Neon."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
from typing import Any

from dialin.config import load_settings, mask_database_url
from dialin.db import admin_connection

MIGRATION_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename text PRIMARY KEY,
    checksum text NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT now()
)
"""


def migration_files() -> list[Path]:
    """Return migration files in deterministic order."""

    return sorted(Path("migrations").glob("*.sql"))


def apply_migrations(
    database_url: str,
    *,
    only: str | None = None,
    plan: bool = False,
    baseline_through: str | None = None,
) -> None:
    """Run pending SQL migrations in one transaction."""

    files = migration_files()
    if not files:
        raise RuntimeError("No migrations found.")

    with admin_connection(database_url) as conn:
        _ensure_migration_table(conn)
        applied = _applied_migrations(conn)
        if baseline_through is not None and plan:
            applied = applied | {path.name for path in _files_through(files, baseline_through)}
        elif baseline_through is not None:
            _baseline_existing(conn, files, baseline_through)
            applied = _applied_migrations(conn)
        selected = _selected_files(files, only)
        pending = [path for path in selected if path.name not in applied]
        if plan:
            _print_plan(selected, applied)
            return
        for path in pending:
            sql = path.read_text(encoding="utf-8")
            conn.execute(sql)
            _record_migration(conn, path)
            print(f"applied {path}")
        if not pending:
            print("no pending migrations")


def main() -> None:
    """Parse CLI options and apply migrations."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--target", choices=["local", "neon"], default="local")
    parser.add_argument("--only", help="Apply one migration file by filename, stem, or prefix.")
    parser.add_argument(
        "--plan",
        action="store_true",
        help="Print migration status without applying.",
    )
    parser.add_argument(
        "--baseline-through",
        help=(
            "Mark existing migrations through this filename/stem/prefix as already applied, "
            "then apply later pending migrations."
        ),
    )
    args = parser.parse_args()

    settings = load_settings()
    print(f"target={args.target} database={mask_database_url(settings.migration_database_url)}")
    apply_migrations(
        settings.migration_database_url,
        only=args.only,
        plan=args.plan,
        baseline_through=args.baseline_through,
    )


def _ensure_migration_table(conn: Any) -> None:
    """Create the migration ledger if the database does not have one."""

    conn.execute(MIGRATION_TABLE_SQL)


def _applied_migrations(conn: Any) -> set[str]:
    """Return migration filenames already recorded in the ledger."""

    rows = conn.execute("SELECT filename FROM schema_migrations").fetchall()
    return {str(row["filename"]) for row in rows}


def _record_migration(conn: Any, path: Path) -> None:
    """Record one successfully applied migration."""

    conn.execute(
        """
        INSERT INTO schema_migrations (filename, checksum)
        VALUES (%s, %s)
        ON CONFLICT (filename) DO UPDATE
        SET checksum = EXCLUDED.checksum,
            applied_at = now()
        """,
        (path.name, _checksum(path)),
    )


def _baseline_existing(conn: Any, files: list[Path], through: str) -> None:
    """Mark already-applied migrations through a known point without executing them."""

    for path in _files_through(files, through):
        conn.execute(
            """
            INSERT INTO schema_migrations (filename, checksum)
            VALUES (%s, %s)
            ON CONFLICT (filename) DO NOTHING
            """,
            (path.name, _checksum(path)),
        )
        print(f"baselined {path}")


def _files_through(files: list[Path], through: str) -> list[Path]:
    """Return all migration files through the requested file."""

    for index, path in enumerate(files):
        if _matches_migration(path, through):
            return files[: index + 1]
    raise ValueError(f"Unknown migration for --baseline-through: {through}")


def _selected_files(files: list[Path], only: str | None) -> list[Path]:
    """Return the files targeted by this migration run."""

    if only is None:
        return files
    matches = [path for path in files if _matches_migration(path, only)]
    if not matches:
        raise ValueError(f"Unknown migration for --only: {only}")
    if len(matches) > 1:
        names = ", ".join(path.name for path in matches)
        raise ValueError(f"--only matched multiple migrations: {names}")
    return matches


def _matches_migration(path: Path, value: str) -> bool:
    """Return whether a user-supplied migration identifier matches a path."""

    normalized = value.strip()
    return path.name == normalized or path.stem == normalized or path.name.startswith(normalized)


def _print_plan(files: list[Path], applied: set[str]) -> None:
    """Print migration status for the selected files."""

    for path in files:
        status = "applied" if path.name in applied else "pending"
        print(f"{status} {path}")


def _checksum(path: Path) -> str:
    """Return a SHA-256 checksum for a migration file."""

    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    main()
