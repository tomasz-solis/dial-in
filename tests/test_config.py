"""Tests for runtime configuration loading."""

from __future__ import annotations

from pathlib import Path

import pytest

from dialin.config import load_settings


def test_load_settings_can_override_exported_database_url(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Streamlit runtime settings should override a stale exported owner URL."""

    env_file = tmp_path / ".env.local"
    env_file.write_text(
        "\n".join(
            [
                "DATABASE_URL=postgresql://dialin_app:app@example.test/dialin",
                "MIGRATION_DATABASE_URL=postgresql://dialin_owner:owner@example.test/dialin",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DATABASE_URL", "postgresql://neondb_owner:owner@example.test/neondb")

    settings = load_settings(env_file, override=True)

    assert settings.database_url == "postgresql://dialin_app:app@example.test/dialin"
