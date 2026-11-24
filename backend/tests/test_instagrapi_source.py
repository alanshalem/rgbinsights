"""Adapter error mapping for get_post and the relogin hook.

Uses a stub client injected into the adapter (no network): the stub mimics
instagrapi's media_info, which routes private-API failures through the
handle_exception hook and then silently falls back to the public endpoint.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any

import pytest
from app.infrastructure.config.settings import Settings
from app.infrastructure.instagram.errors import (
    IpBlockedError,
    LoginRequiredError,
    PostNotFoundError,
)
from app.infrastructure.instagram.instagrapi_source import InstagrapiInstagramSource
from app.infrastructure.instagram.session import _make_handle_exception
from instagrapi.exceptions import (
    BadPassword,
    ClientError,
    ClientLoginRequired,
    LoginRequired,
    MediaNotFound,
    ReloginAttemptExceeded,
)

URL = "https://www.instagram.com/p/DfZ69nZEeFv/"
RELOGIN_TYPEERROR = (
    "int() argument must be a string, a bytes-like object or a real number, not 'NoneType'"
)


@pytest.fixture(autouse=True)
def _isolated_guard_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # The adapter persists breaker/budget state; keep it out of the repo.
    monkeypatch.setenv("IG_GUARD_FILE", str(tmp_path / "ig_guard.json"))


def _settings() -> Settings:
    return Settings(use_fake_instagram=False, ig_username="user", ig_password="pass")


class StubClient:
    """Mimics the parts of instagrapi.Client that get_post touches."""

    def __init__(
        self,
        settings: Settings,
        media_error: Exception,
        relogin_error: Exception | None = None,
    ) -> None:
        self.handle_exception = _make_handle_exception(settings)
        self._media_error = media_error
        self._relogin_error = relogin_error
        self.relogin_calls = 0

    def media_pk_from_url(self, url: str) -> str:
        return "123"

    def relogin(self) -> bool:
        self.relogin_calls += 1
        if self._relogin_error is not None:
            raise self._relogin_error
        return True

    def media_info(self, media_pk: str) -> Any:
        # instagrapi: the private request fails with LoginRequired -> hook runs;
        # whatever the hook raises is swallowed and the public path is tried.
        with contextlib.suppress(Exception):  # mirrors instagrapi's broad fallback
            self.handle_exception(self, LoginRequired())
        raise self._media_error

    def direct_send(self, text: str, user_ids: list[int]) -> None:
        # instagrapi does not swallow hook errors on sends: they propagate.
        self.handle_exception(self, LoginRequired())


def _source_with(client: object) -> InstagrapiInstagramSource:
    source = InstagrapiInstagramSource(_settings())
    source._client = client
    return source


def test_get_post_reports_login_error_when_relogin_crashes() -> None:
    client = StubClient(
        _settings(), ClientError("public fallback failed"), TypeError(RELOGIN_TYPEERROR)
    )
    source = _source_with(client)

    with pytest.raises(LoginRequiredError) as info:
        source.get_post(URL)

    assert not isinstance(info.value, PostNotFoundError)
    assert "sessionid" in str(info.value)
    assert "int()" not in str(info.value)
    assert source._client is None  # broken client dropped; next call logs in again


def test_handle_exception_turns_relogin_crash_into_login_error() -> None:
    client = StubClient(_settings(), ClientError(), TypeError(RELOGIN_TYPEERROR))

    with pytest.raises(LoginRequiredError) as info:
        client.handle_exception(client, LoginRequired())

    assert isinstance(info.value.__cause__, TypeError)


@pytest.mark.parametrize(
    "exc",
    [LoginRequired(), ReloginAttemptExceeded(), ClientLoginRequired()],
    ids=["LoginRequired", "ReloginAttemptExceeded", "ClientLoginRequired"],
)
def test_get_post_maps_session_errors_to_login_required(exc: Exception) -> None:
    source = _source_with(StubClient(_settings(), exc))

    with pytest.raises(LoginRequiredError) as info:
        source.get_post(URL)

    assert not isinstance(info.value, PostNotFoundError)
    assert source._client is None


# -- previous behaviour that must still hold -------------------------------


def test_get_post_media_not_found_is_post_not_found() -> None:
    client = StubClient(_settings(), MediaNotFound("gone"))
    source = _source_with(client)

    with pytest.raises(PostNotFoundError):
        source.get_post(URL)

    assert source._client is client  # a missing post is not a session problem


def test_get_post_other_client_error_is_still_post_not_found() -> None:
    client = StubClient(_settings(), ClientError("not available"))
    source = _source_with(client)

    with pytest.raises(PostNotFoundError):
        source.get_post(URL)

    assert client.relogin_calls == 1  # relogin succeeded; the post itself failed
    assert source._client is client


def test_handle_exception_still_reraises_non_login_errors() -> None:
    client = StubClient(_settings(), ClientError())
    original = ClientError("throttled")

    with pytest.raises(ClientError) as info:
        client.handle_exception(client, original)

    assert info.value is original
    assert client.relogin_calls == 0


def test_send_dm_relogin_ip_block_stays_ip_blocked() -> None:
    blocked = BadPassword("Your IP address is on a blacklist")
    client = StubClient(_settings(), ClientError(), blocked)
    source = _source_with(client)

    with pytest.raises(IpBlockedError):
        source.send_dm("5", "hola")

    assert source._client is client  # an IP block is not a dead session


def test_send_dm_relogin_crash_is_login_error_and_drops_client() -> None:
    client = StubClient(_settings(), ClientError(), TypeError(RELOGIN_TYPEERROR))
    source = _source_with(client)

    with pytest.raises(LoginRequiredError) as info:
        source.send_dm("5", "hola")

    assert "sessionid" in str(info.value)
    assert source._client is None


def test_handle_exception_successful_relogin_returns_quietly() -> None:
    client = StubClient(_settings(), ClientError())

    assert client.handle_exception(client, LoginRequired()) is None
    assert client.relogin_calls == 1
