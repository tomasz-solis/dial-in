"""Provision the low-privilege ``dialin_app`` role for DB-backed CI tests.

The RLS isolation tests (``tests/test_rls_isolation.py``) need the app role to
exist *before* migrations run, because each migration grants table privileges to
it inside an ``IF EXISTS (... rolname = 'dialin_app')`` guard. Locally that role
is created by ``docker/init/001_roles.sql``; in CI the Postgres service container
starts empty, so this script creates it idempotently from the owner connection.

It reads the owner/admin URL from ``TEST_DATABASE_URL`` (the same variable the
test harness uses) and the role name/password from ``APP_DATABASE_ROLE`` /
``APP_DATABASE_PASSWORD`` (sane defaults). It is intentionally CI-only and never
imported by the app.
"""

from __future__ import annotations

import os

import psycopg
from psycopg import sql


def main() -> None:
    """Create the app role if it does not already exist."""

    owner_url = os.environ.get("TEST_DATABASE_URL")
    if not owner_url:
        raise RuntimeError("TEST_DATABASE_URL is required to create the app role.")
    role = os.environ.get("APP_DATABASE_ROLE", "dialin_app")
    password = os.environ.get("APP_DATABASE_PASSWORD", "dialin_app")

    with psycopg.connect(owner_url, autocommit=True) as conn:
        exists = conn.execute(
            "SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)
        ).fetchone()
        if exists:
            print(f"role {role!r} already exists")
            return
        conn.execute(
            sql.SQL("CREATE ROLE {role} LOGIN PASSWORD {password}").format(
                role=sql.Identifier(role),
                password=sql.Literal(password),
            )
        )
        print(f"created role {role!r}")


if __name__ == "__main__":
    main()
