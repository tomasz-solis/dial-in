"""DB-backed Row-Level Security isolation tests (PRD section 10.7-10.8).

These prove the central tenant-safety claim against real Postgres: with the
low-privilege app role and only ``app.current_account_id`` set, one account can
neither read nor write another account's rows. They skip unless both
``TEST_DATABASE_URL`` and ``TEST_APP_DATABASE_URL`` are configured (see
``tests/conftest.py``).
"""

from __future__ import annotations

from datetime import date

import psycopg
import pytest

from dialin.db import account_connection, assert_not_owner_connection


def test_account_sees_only_its_own_rows(
    rls_app_url: str, rls_seeded_accounts: dict[str, str]
) -> None:
    """An unfiltered read returns only the session account's rows."""

    with account_connection(rls_app_url, rls_seeded_accounts["a"]) as conn:
        rows = conn.execute("SELECT account_id FROM daily_metrics").fetchall()
    assert rows, "account A should see its own seeded row"
    assert {row["account_id"] for row in rows} == {rls_seeded_accounts["a"]}


def test_account_cannot_read_another_accounts_rows(
    rls_app_url: str, rls_seeded_accounts: dict[str, str]
) -> None:
    """Even an explicit cross-account filter returns nothing under RLS."""

    with account_connection(rls_app_url, rls_seeded_accounts["b"]) as conn:
        rows = conn.execute(
            "SELECT * FROM daily_metrics WHERE account_id = %s",
            (rls_seeded_accounts["a"],),
        ).fetchall()
    assert rows == []


def test_account_cannot_write_into_another_account(
    rls_app_url: str, rls_seeded_accounts: dict[str, str]
) -> None:
    """A WITH CHECK violation blocks inserting a row for a different account."""

    with (
        pytest.raises(psycopg.Error),
        account_connection(rls_app_url, rls_seeded_accounts["b"]) as conn,
    ):
        conn.execute(
            """
            INSERT INTO daily_metrics
                (account_id, location_id, date, timezone, is_open)
            VALUES (%s, %s, %s, 'Europe/Madrid', true)
            """,
            (rls_seeded_accounts["a"], rls_seeded_accounts["location"], date(2026, 1, 2)),
        )


def test_app_role_passes_low_privilege_guard(rls_app_url: str) -> None:
    """The app-role connection is accepted by the startup guard."""

    assert_not_owner_connection(rls_app_url)


def test_admin_url_is_rejected_as_app_connection(rls_admin_url: str) -> None:
    """The owner/admin connection must be refused as an app runtime connection."""

    with pytest.raises(RuntimeError):
        assert_not_owner_connection(rls_admin_url)
