"""Tests for append-only recommendation repository behavior."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from typing import Any

from dialin.engine import RecommendationResult, stable_hash
from dialin.repository import recommendations as recommendation_repo


def test_insert_recommendation_set_supersedes_prior_active_row(monkeypatch: Any) -> None:
    """Recomputing a recommendation should preserve the prior row and insert a new one."""

    fake_conn = _FakeConnection()

    @contextmanager
    def fake_account_connection(_database_url: str, _account_id: str) -> Iterator[_FakeConnection]:
        yield fake_conn

    fetch_all_calls: list[tuple[str, Any]] = []
    fetch_one_calls: list[tuple[str, Any]] = []

    def fake_fetch_all(_conn: _FakeConnection, query: str, params: Any) -> list[dict[str, Any]]:
        fetch_all_calls.append((query, params))
        if "SELECT recommendation_id" in query:
            return [{"recommendation_id": "old-1"}]
        return []

    def fake_fetch_one(
        _conn: _FakeConnection,
        query: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        fetch_one_calls.append((query, params))
        return {"recommendation_id": "new-1"}

    monkeypatch.setattr(recommendation_repo, "account_connection", fake_account_connection)
    monkeypatch.setattr(recommendation_repo, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(recommendation_repo, "fetch_one", fake_fetch_one)

    inserted = recommendation_repo.insert_recommendation_set(
        "postgresql://example",
        [_recommendation_result()],
    )

    sql_text = "\n".join(
        [query for query, _params in fetch_all_calls]
        + [query for query, _params in fetch_one_calls]
        + [query for query, _params in fake_conn.calls]
    )
    assert inserted == ["new-1"]
    assert "AND is_active = true" in sql_text
    assert "SET is_active = false" in sql_text
    assert "superseded_at" in sql_text
    assert "input_snapshot" in sql_text
    assert "config_snapshot" in sql_text
    assert "ON CONFLICT" not in sql_text
    assert fake_conn.calls[-1][1] == ("new-1", ["old-1"])


def test_active_recommendation_fetch_filters_superseded_rows(monkeypatch: Any) -> None:
    """Normal app reads should only fetch active recommendations for the target date."""

    fake_conn = _FakeConnection()

    @contextmanager
    def fake_account_connection(_database_url: str, _account_id: str) -> Iterator[_FakeConnection]:
        yield fake_conn

    fetch_all_calls: list[tuple[str, Any]] = []

    def fake_fetch_all(_conn: _FakeConnection, query: str, params: Any) -> list[dict[str, Any]]:
        fetch_all_calls.append((query, params))
        return []

    monkeypatch.setattr(recommendation_repo, "account_connection", fake_account_connection)
    monkeypatch.setattr(recommendation_repo, "fetch_all", fake_fetch_all)

    rows = recommendation_repo.fetch_active_recommendations_for_date(
        "postgresql://example",
        "acct",
        "loc",
        date(2026, 6, 1),
    )

    assert rows == []
    assert "AND is_active = true" in fetch_all_calls[0][0]


def test_recommendation_build_payload_uses_bounded_windows(monkeypatch: Any) -> None:
    """The build payload should read trailing history and target-date context only."""

    fake_conn = _FakeConnection()

    @contextmanager
    def fake_account_connection(_database_url: str, _account_id: str) -> Iterator[_FakeConnection]:
        yield fake_conn

    fetch_all_calls: list[tuple[str, Any]] = []

    def fake_fetch_all(_conn: _FakeConnection, query: str, params: Any) -> list[dict[str, Any]]:
        fetch_all_calls.append((query, params))
        return []

    monkeypatch.setattr(recommendation_repo, "account_connection", fake_account_connection)
    monkeypatch.setattr(recommendation_repo, "fetch_all", fake_fetch_all)

    payload = recommendation_repo.fetch_recommendation_build_payload(
        "postgresql://example",
        "acct",
        "loc",
        date(2026, 6, 1),
    )

    assert set(payload) == {
        "daily_metrics",
        "daily_category_metrics",
        "weather",
        "events",
        "category_economics",
    }
    assert fetch_all_calls[0][1] == ("acct", "loc", date(2025, 6, 1), date(2026, 6, 1))
    assert fetch_all_calls[1][1] == ("acct", "loc", date(2025, 6, 1), date(2026, 6, 1))
    assert fetch_all_calls[2][1] == ("acct", "loc", date(2026, 6, 1))
    assert fetch_all_calls[3][1] == ("acct", "loc", date(2026, 6, 1))
    assert fetch_all_calls[4][1] == ("acct", "loc", date(2026, 6, 1), date(2026, 6, 1))


class _FakeConnection:
    """Minimal connection double that records raw SQL execute calls."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    def execute(self, query: str, params: Any = None) -> None:
        self.calls.append((query, params))


def _recommendation_result() -> RecommendationResult:
    """Return a compact recommendation result for repository tests."""

    input_snapshot: dict[str, Any] = {
        "target_date": "2026-06-01",
        "category": "sweet",
        "traffic_mean": 120.0,
    }
    config_snapshot: dict[str, Any] = {
        "model_version": "v1_rules_newsvendor",
        "economics": {"values_source": "default"},
    }
    return RecommendationResult(
        account_id="acct",
        location_id="loc",
        date=date(2026, 6, 1),
        category="sweet",
        recommended_prep=42,
        demand_p50=38,
        demand_p_lower=30,
        demand_p_upper=55,
        service_quantile=0.78,
        confidence="Medium",
        risk_flag="normal",
        top_drivers=[],
        model_version="v1_rules_newsvendor",
        input_snapshot_id=stable_hash(input_snapshot),
        config_snapshot_id=stable_hash(config_snapshot),
        input_snapshot=input_snapshot,
        config_snapshot=config_snapshot,
        generated_at=datetime(2026, 6, 1, 6, 30, tzinfo=UTC),
    )
