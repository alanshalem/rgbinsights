"""S20/L25/L27/L28: the Instagram source. The app always uses the real account
(it makes no Instagram request until a sessionid is pasted). The old IG_SOURCE and
USE_FAKE_INSTAGRAM are no longer read at all, so an old .env can never leave the
app stuck on invented data; only RGB_DEV_FAKE_INSTAGRAM=1 (development/tests)
selects the fake source."""

from __future__ import annotations

from pathlib import Path

import pytest
from app.api.routers.health import health
from app.infrastructure.config.settings import Settings

_SOURCE_VARS = ("IG_SOURCE", "USE_FAKE_INSTAGRAM", "RGB_DEV_FAKE_INSTAGRAM")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (*_SOURCE_VARS, "IG_USERNAME", "IG_PASSWORD", "IG_SESSIONID"):
        monkeypatch.delenv(name, raising=False)


def _from_file(tmp_path: Path, text: str) -> Settings:
    env_file = tmp_path / "settings_file.txt"  # any dotenv-format file
    env_file.write_text(text, encoding="utf-8")
    return Settings(_env_file=env_file)


def test_default_is_the_real_source() -> None:
    settings = Settings(_env_file=None)
    assert settings.ig_source == "instagrapi"
    assert not settings.is_fake


@pytest.mark.parametrize(
    "text",
    [
        "USE_FAKE_INSTAGRAM=true\n",  # copied from the old .env.example
        "IG_SOURCE=fake\n",
        "IG_SOURCE=FAKE\nUSE_FAKE_INSTAGRAM=true\n",
        "USE_FAKE_INSTAGRAM=false\nIG_SOURCE=fake\n",
        "IG_SOURCE=instagrapi\n",
        "",
    ],
)
def test_old_source_variables_in_an_env_file_are_ignored(tmp_path: Path, text: str) -> None:
    settings = _from_file(tmp_path, text)
    assert (settings.ig_source, settings.is_fake) == ("instagrapi", False)
    dumped = settings.model_dump()
    assert "use_fake_instagram" not in dumped and "ig_source" not in dumped


def test_old_source_variables_in_the_process_environment_are_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("USE_FAKE_INSTAGRAM", "true")
    monkeypatch.setenv("IG_SOURCE", "fake")
    assert Settings(_env_file=None).ig_source == "instagrapi"


def test_only_the_dev_override_selects_the_fake_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert _from_file(tmp_path, "RGB_DEV_FAKE_INSTAGRAM=1\n").ig_source == "fake"
    monkeypatch.setenv("RGB_DEV_FAKE_INSTAGRAM", "1")
    assert Settings(_env_file=None).is_fake
    monkeypatch.setenv("RGB_DEV_FAKE_INSTAGRAM", "0")
    assert not Settings(_env_file=None).is_fake
    # Tests set the field directly (no environment involved).
    monkeypatch.delenv("RGB_DEV_FAKE_INSTAGRAM")
    assert Settings(_env_file=None, dev_fake_instagram=True).ig_source == "fake"


_OLD_LOGIN_VARS = ("IG_USERNAME", "IG_PASSWORD", "IG_2FA_SECRET", "IG_SESSIONID")


def test_old_login_variables_are_no_longer_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """L24: the only way in is a sessionid pasted in the app; an older env file
    (or process environment) with credentials or a sessionid is ignored."""
    for name in _OLD_LOGIN_VARS:
        monkeypatch.setenv(name, f"env-{name}")
    settings = _from_file(tmp_path, "".join(f"{n}=file-{n}\n" for n in _OLD_LOGIN_VARS))

    dumped = settings.model_dump()
    for name in _OLD_LOGIN_VARS:
        assert not hasattr(settings, name.lower())
        assert name.lower() not in dumped
    assert not any("env-IG_" in str(v) or "file-IG_" in str(v) for v in dumped.values())


def test_country_locale_and_timezone_are_fixed_to_argentina(tmp_path: Path) -> None:
    from datetime import timedelta

    from app.infrastructure.config import settings as module

    settings = _from_file(tmp_path, "IG_COUNTRY=US\nIG_LOCALE=en_US\nIG_TIMEZONE_OFFSET=0\n")

    assert (module.IG_COUNTRY, module.IG_LOCALE, module.IG_TIMEZONE_OFFSET) == (
        "AR",
        "es_AR",
        -10800,
    )
    assert settings.local_tz().utcoffset(None) == timedelta(hours=-3)
    assert "ig_country" not in settings.model_dump()


def test_health_reports_the_resolved_source() -> None:
    assert health(Settings(_env_file=None)).using_fake_instagram is False
    dev = Settings(_env_file=None, dev_fake_instagram=True)
    assert health(dev).using_fake_instagram is True
