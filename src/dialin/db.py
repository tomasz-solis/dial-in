"""Postgres access helpers with tenant scoping built in."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg import Connection
from psycopg.rows import dict_row

DbParams = Sequence[Any] | Mapping[str, Any]
DbRow = dict[str, Any]


@contextmanager
def account_connection(database_url: str, account_id: str) -> Iterator[Connection[Any]]:
    """Open a transaction scoped to one account through the RLS account setting."""

    with psycopg.connect(database_url, row_factory=dict_row) as conn, conn.transaction():
        conn.execute("SELECT set_config('app.current_account_id', %s, true)", (account_id,))
        yield conn


@contextmanager
def admin_connection(database_url: str) -> Iterator[Connection[Any]]:
    """Open an admin transaction for migrations and seed loading."""

    with psycopg.connect(database_url, row_factory=dict_row) as conn, conn.transaction():
        yield conn


def fetch_all(conn: Connection[Any], query: str, params: DbParams | None = None) -> list[DbRow]:
    """Fetch all rows from a query as dictionaries."""

    rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def fetch_one(conn: Connection[Any], query: str, params: DbParams | None = None) -> DbRow | None:
    """Fetch a single row from a query as a dictionary."""

    row = conn.execute(query, params).fetchone()
    return None if row is None else dict(row)


def execute_many(conn: Connection[Any], query: str, rows: Sequence[DbParams]) -> None:
    """Execute the same statement for a batch of parameter sets."""

    if not rows:
        return
    with conn.cursor() as cur:
        cur.executemany(query, rows)


def resolve_account_id(database_url: str, auth_subject: str) -> str | None:
    """Resolve a logged-in auth subject to its tenant account."""

    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        row = conn.execute(
            """
            SELECT account_id
            FROM account_members
            WHERE auth_subject = %s
            """,
            (auth_subject,),
        ).fetchone()
    return None if row is None else str(row["account_id"])


def assert_not_owner_connection(database_url: str, app_role: str = "dialin_app") -> None:
    """Reject app startup when DATABASE_URL is not the low-privilege app role."""

    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        row = conn.execute("SELECT current_user AS user_name").fetchone()
    user_name = "" if row is None else str(row["user_name"])
    if user_name != app_role:
        raise RuntimeError(
            f"DATABASE_URL must use the low-privilege {app_role!r} role; got {user_name!r}."
        )
