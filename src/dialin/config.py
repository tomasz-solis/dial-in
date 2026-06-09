"""Configuration helpers shared by scripts and the Streamlit app."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    """Runtime settings loaded from environment variables."""

    database_url: str
    migration_database_url: str
    app_database_role: str


def load_settings(env_file: str | Path = ".env", *, override: bool = False) -> Settings:
    """Load database settings, falling back to DATABASE_URL for bootstrap migrations."""

    path = Path(env_file)
    if path.exists():
        load_dotenv(path, override=override)

    database_url = os.environ.get("DATABASE_URL", "")
    migration_database_url = os.environ.get("MIGRATION_DATABASE_URL", database_url)
    app_database_role = os.environ.get("APP_DATABASE_ROLE", "dialin_app")

    if not database_url:
        raise RuntimeError("DATABASE_URL is required.")
    if not migration_database_url:
        raise RuntimeError("MIGRATION_DATABASE_URL or DATABASE_URL is required.")

    return Settings(
        database_url=database_url,
        migration_database_url=migration_database_url,
        app_database_role=app_database_role,
    )


def mask_database_url(database_url: str) -> str:
    """Return a connection string with the password removed for logs."""

    parsed = urlsplit(database_url)
    if "@" not in parsed.netloc:
        return database_url
    userinfo, hostinfo = parsed.netloc.rsplit("@", 1)
    username = userinfo.split(":", 1)[0]
    return urlunsplit((parsed.scheme, f"{username}:***@{hostinfo}", parsed.path, parsed.query, ""))
