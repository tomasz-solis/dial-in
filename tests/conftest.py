"""Shared pytest fixtures, including the optional DB-backed RLS harness.

The RLS isolation tests need a real Postgres database because Row-Level Security
is enforced by Postgres, not by application code. They are opt-in: set
``TEST_DATABASE_URL`` to an admin/owner connection (used to migrate and seed) and
``TEST_APP_DATABASE_URL`` to the low-privilege app-role connection (the one the
RLS policies actually constrain). When either is missing the tests skip cleanly,
so the default ``uv run pytest`` stays green without a database.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import date

import pytest

from dialin.db import admin_connection

RLS_ACCOUNT_A = "acct_rls_a"
RLS_ACCOUNT_B = "acct_rls_b"
RLS_ACCOUNTS = (RLS_ACCOUNT_A, RLS_ACCOUNT_B)
RLS_LOCATION = "loc_rls_main"


@pytest.fixture(scope="session")
def rls_admin_url() -> str:
    """Return the admin/owner test connection or skip if unconfigured."""

    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set; skipping DB-backed RLS tests")
    return url


@pytest.fixture(scope="session")
def rls_app_url() -> str:
    """Return the low-privilege app-role test connection or skip if unconfigured."""

    url = os.environ.get("TEST_APP_DATABASE_URL")
    if not url:
        pytest.skip("TEST_APP_DATABASE_URL not set; skipping DB-backed RLS tests")
    return url


@pytest.fixture(scope="session")
def rls_seeded_accounts(rls_admin_url: str) -> Iterator[dict[str, str]]:
    """Migrate the test database and seed two isolated tenants for RLS checks."""

    from scripts.migrate import apply_migrations

    apply_migrations(rls_admin_url)
    with admin_connection(rls_admin_url) as conn:
        _seed_rls_accounts(conn)
    try:
        yield {"a": RLS_ACCOUNT_A, "b": RLS_ACCOUNT_B, "location": RLS_LOCATION}
    finally:
        with admin_connection(rls_admin_url) as conn:
            conn.execute(
                "DELETE FROM accounts WHERE account_id = ANY(%s)",
                (list(RLS_ACCOUNTS),),
            )


def _seed_rls_accounts(conn: object) -> None:
    """Idempotently seed two accounts, each with one location and one day."""

    for account_id in RLS_ACCOUNTS:
        conn.execute(  # type: ignore[attr-defined]
            "INSERT INTO accounts (account_id, name) VALUES (%s, %s) "
            "ON CONFLICT (account_id) DO NOTHING",
            (account_id, f"RLS test {account_id}"),
        )
        conn.execute(  # type: ignore[attr-defined]
            """
            INSERT INTO locations
                (account_id, location_id, name, timezone, city, country, open_days)
            VALUES (%s, %s, 'Main', 'Europe/Madrid', 'Test', 'ES', %s)
            ON CONFLICT (account_id, location_id) DO NOTHING
            """,
            (account_id, RLS_LOCATION, [0, 1, 2, 3, 4, 5, 6]),
        )
        conn.execute(  # type: ignore[attr-defined]
            """
            INSERT INTO daily_metrics
                (account_id, location_id, date, timezone, is_open, drinks_sold)
            VALUES (%s, %s, %s, 'Europe/Madrid', true, 100)
            ON CONFLICT (account_id, location_id, date) DO NOTHING
            """,
            (account_id, RLS_LOCATION, date(2026, 1, 1)),
        )
