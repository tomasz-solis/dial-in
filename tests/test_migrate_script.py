"""Tests for the migration runner safety controls."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from scripts import migrate


def test_selected_files_accept_filename_stem_or_prefix(tmp_path: Path) -> None:
    """Operators should not need to type a full migration filename."""

    files = _migration_paths(tmp_path)

    assert migrate._selected_files(files, "007").pop().name == "007_new.sql"
    assert migrate._selected_files(files, "007_new").pop().name == "007_new.sql"
    assert migrate._selected_files(files, "007_new.sql").pop().name == "007_new.sql"


def test_baseline_through_returns_ordered_prefix(tmp_path: Path) -> None:
    """Existing databases should be baselined through a known migration point."""

    files = _migration_paths(tmp_path)

    selected = migrate._files_through(files, "006")

    assert [path.name for path in selected] == ["001_init.sql", "006_pos.sql"]


def test_baseline_through_applies_later_pending_migrations(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    """Baselining 001-006 should let a live DB apply only newer migrations."""

    files = _migration_paths(tmp_path)
    fake_conn = _FakeConnection()

    @contextmanager
    def fake_admin_connection(_database_url: str) -> Iterator[_FakeConnection]:
        yield fake_conn

    monkeypatch.setattr(migrate, "migration_files", lambda: files)
    monkeypatch.setattr(migrate, "admin_connection", fake_admin_connection)

    migrate.apply_migrations("postgresql://example", baseline_through="006")

    assert "001_init.sql" in fake_conn.applied
    assert "006_pos.sql" in fake_conn.applied
    assert "007_new.sql" in fake_conn.applied
    assert fake_conn.migration_sql == ["-- 007"]


def test_plan_with_baseline_through_does_not_write(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    """Plan mode must not mutate the migration ledger."""

    files = _migration_paths(tmp_path)
    fake_conn = _FakeConnection()

    @contextmanager
    def fake_admin_connection(_database_url: str) -> Iterator[_FakeConnection]:
        yield fake_conn

    monkeypatch.setattr(migrate, "migration_files", lambda: files)
    monkeypatch.setattr(migrate, "admin_connection", fake_admin_connection)

    migrate.apply_migrations("postgresql://example", baseline_through="006", plan=True)

    assert fake_conn.applied == set()
    assert fake_conn.migration_sql == []


class _FakeResult:
    """Tiny result object for fake DB calls."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def fetchall(self) -> list[dict[str, Any]]:
        return self.rows


class _FakeConnection:
    """Fake migration connection that records SQL and migration ledger writes."""

    def __init__(self) -> None:
        self.applied: set[str] = set()
        self.migration_sql: list[str] = []

    def execute(self, query: str, params: Any = None) -> _FakeResult:
        normalized = query.strip()
        if normalized.startswith("SELECT filename FROM schema_migrations"):
            return _FakeResult([{"filename": filename} for filename in sorted(self.applied)])
        if normalized.startswith("INSERT INTO schema_migrations") and params is not None:
            self.applied.add(str(params[0]))
            return _FakeResult([])
        if normalized.startswith("--"):
            self.migration_sql.append(normalized)
        return _FakeResult([])


def _migration_paths(tmp_path: Path) -> list[Path]:
    """Create fake migration files in deterministic order."""

    paths = [
        tmp_path / "001_init.sql",
        tmp_path / "006_pos.sql",
        tmp_path / "007_new.sql",
    ]
    for path in paths:
        path.write_text(f"-- {path.stem.split('_', 1)[0]}", encoding="utf-8")
    return paths
