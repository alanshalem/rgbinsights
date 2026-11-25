"""S20: one data-source setting (IG_SOURCE), still honouring old .env files."""

from __future__ import annotations

from pathlib import Path

import pytest
from app.api.routers.health import health
from app.infrastructure.config.settings import Settings


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("IG_SOURCE", "USE_FAKE_INSTAGRAM", "IG_USERNAME", "IG_PASSWORD"):
        monkeypatch.delenv(name, raising=False)


def _from_file(tmp_path: Path, text: str) -> Settings:
    env_file = tmp_path / "settings_file.txt"  # any dotenv-format file
    env_file.write_text(text, encoding="utf-8")
    return Settings(_env_file=env_file)


def test_default_is_the_fake_source() -> None:
    settings = Settings(_env_file=None)
    assert settings.ig_source == "fake"
    assert settings.is_fake


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("USE_FAKE_INSTAGRAM=false\n", "instagrapi"),  # the original way to go real
        ("USE_FAKE_INSTAGRAM=false\nIG_SOURCE=instagrapi\n", "instagrapi"),
        ("USE_FAKE_INSTAGRAM=false\nIG_SOURCE=\n", "instagrapi"),  # empty falls back
        ("USE_FAKE_INSTAGRAM=true\nIG_SOURCE=instagrapi\n", "instagrapi"),  # IG_SOURCE wins
        ("USE_FAKE_INSTAGRAM=false\nIG_SOURCE=playwright\n", "instagrapi"),  # old value
        ("IG_SOURCE=instagrapi\n", "instagrapi"),
        ("USE_FAKE_INSTAGRAM=false\nIG_SOURCE=fake\n", "fake"),
        ("USE_FAKE_INSTAGRAM=true\n", "fake"),
        ("IG_SOURCE=FAKE\n", "fake"),
        ("", "fake"),
    ],
)
def test_existing_env_files_keep_selecting_the_same_source(
    tmp_path: Path, text: str, expected: str
) -> None:
    assert _from_file(tmp_path, text).ig_source == expected


def test_legacy_flag_from_the_process_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("USE_FAKE_INSTAGRAM", "false")
    assert Settings(_env_file=None).ig_source == "instagrapi"
    monkeypatch.setenv("IG_SOURCE", "fake")
    assert Settings(_env_file=None).ig_source == "fake"


def test_has_password_login_needs_both_values() -> None:
    assert Settings(_env_file=None, ig_username="u", ig_password="p").has_password_login
    assert not Settings(_env_file=None, ig_username="u", ig_password="  ").has_password_login
    assert not Settings(_env_file=None, ig_username="", ig_password="p").has_password_login


def test_health_reports_the_resolved_source() -> None:
    assert health(Settings(_env_file=None)).using_fake_instagram is True
    real = Settings(_env_file=None, ig_source="instagrapi")  # USE_FAKE_INSTAGRAM unset
    assert health(real).using_fake_instagram is False


def test_ig_source_fake_wins_over_legacy_false(tmp_path: Path) -> None:
    settings = _from_file(tmp_path, "IG_SOURCE=fake\nUSE_FAKE_INSTAGRAM=false\n")
    assert (settings.ig_source, settings.is_fake) == ("fake", True)
