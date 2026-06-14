"""Tests for repository POS import apply behavior."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from typing import Any

from dialin import repository
from dialin.pos_import import DailySalesRollup, PosImportError, PosImportPreview


def test_apply_pos_import_replaces_rollups_without_touching_category_closeouts(
    monkeypatch: Any,
) -> None:
    """Applying POS imports should update POS rollups and drinks history only."""

    fake_conn = _FakeConnection()

    @contextmanager
    def fake_account_connection(_database_url: str, _account_id: str) -> Iterator[_FakeConnection]:
        yield fake_conn

    monkeypatch.setattr(repository.pos, "account_connection", fake_account_connection)
    preview = PosImportPreview(
        rows_read=4,
        rows_imported=3,
        rows_rejected=1,
        date_start=date(2026, 5, 31),
        date_end=date(2026, 5, 31),
        timestamp_coverage=0.5,
        rollups=(
            DailySalesRollup(date(2026, 5, 31), "drinks", 120, None, None),
            DailySalesRollup(date(2026, 5, 31), "sweet", 42, None, None),
        ),
        errors=(
            PosImportError(5, "no category match", {"Item": "Unknown"}),
        ),
        mapped_totals={"drinks": 120, "sweet": 42, "savory": 0},
    )

    result = repository.apply_pos_import(
        database_url="postgresql://example",
        account_id="acct",
        location_id="loc",
        filename="pos.csv",
        created_by="demo",
        timezone_name="Europe/Madrid",
        preview=preview,
        mapping={"columns": {}, "categories": {}},
    )

    sql_text = "\n".join(query for query, _params in fake_conn.calls)
    assert result["import_run_id"] == "run-1"
    assert "DELETE FROM pos_daily_sales" in sql_text
    assert "INSERT INTO pos_daily_sales" in sql_text
    assert "INSERT INTO daily_metrics" in sql_text
    assert "daily_category_metrics" not in sql_text


def test_imported_drinks_do_not_overwrite_confirmed_closeout(monkeypatch: Any) -> None:
    """POS re-imports should audit conflicts instead of replacing confirmed traffic."""

    fake_conn = _FakeConnection()

    def fake_fetch_one(_conn: _FakeConnection, _query: str, _params: Any) -> dict[str, Any]:
        return {
            "timezone": "Europe/Madrid",
            "is_open": True,
            "drinks_sold": 100,
            "input_source": "confirmed",
            "menu_version": "v1",
        }

    monkeypatch.setattr(repository.pos, "fetch_one", fake_fetch_one)

    repository.pos._upsert_imported_drinks(
        conn=fake_conn,
        account_id="acct",
        location_id="loc",
        business_date=date(2026, 5, 31),
        timezone_name="Europe/Madrid",
        drinks_sold=120,
        recorded_at=datetime(2026, 5, 31, 18, tzinfo=UTC),
        corrected_by="demo",
    )

    sql_text = "\n".join(query for query, _params in fake_conn.calls)
    assert "INSERT INTO data_corrections" in sql_text
    assert "INSERT INTO daily_metrics" not in sql_text
    assert fake_conn.calls[0][1][-1] == "pos import skipped confirmed closeout"


def test_removed_imported_drinks_are_audited_and_imputed(monkeypatch: Any) -> None:
    """A replacement import that omits a prior imported drinks row should leave an audit trail."""

    fake_conn = _FakeConnection()

    def fake_fetch_one(_conn: _FakeConnection, _query: str, _params: Any) -> dict[str, Any]:
        return {
            "timezone": "Europe/Madrid",
            "is_open": True,
            "drinks_sold": 100,
            "input_source": "imported",
            "menu_version": "v1",
        }

    monkeypatch.setattr(repository.pos, "fetch_one", fake_fetch_one)

    repository.pos._clear_removed_imported_drinks(
        conn=fake_conn,
        account_id="acct",
        location_id="loc",
        date_start=date(2026, 5, 31),
        date_end=date(2026, 5, 31),
        replacement_dates=set(),
        recorded_at=datetime(2026, 5, 31, 18, tzinfo=UTC),
        corrected_by="demo",
    )

    sql_text = "\n".join(query for query, _params in fake_conn.calls)
    assert sql_text.count("INSERT INTO data_corrections") == 2
    assert "UPDATE daily_metrics" in sql_text
    assert "input_source = 'imputed'" in sql_text


class _FakeResult:
    """Small fetch result object for repository tests."""

    def __init__(self, row: dict[str, Any] | None = None) -> None:
        """Create a fake result with an optional row."""

        self.row = row

    def fetchone(self) -> dict[str, Any] | None:
        """Return the configured fake row."""

        return self.row


class _FakeConnection:
    """Minimal connection double that records SQL calls."""

    def __init__(self) -> None:
        """Create an empty fake connection."""

        self.calls: list[tuple[str, Any]] = []

    def execute(self, query: str, params: Any = None) -> _FakeResult:
        """Record an execute call and return a fake result."""

        self.calls.append((query, params))
        if "RETURNING import_run_id" in query:
            return _FakeResult({"import_run_id": "run-1"})
        return _FakeResult()
