"""Adapter error mapping for get_post / send_dm and instagrapi's exception hook.

Uses a stub client injected into the adapter (no network): the stub mimics
instagrapi's media_info, which routes private-API failures through the
handle_exception hook and then silently falls back to the public endpoint.
Since L24 there is no relogin: a dead session surfaces as LoginRequiredError,
drops the client and is never retried with a login.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any

import pytest
from app.domain.errors import (
    IpBlockedError,
    LoginRequiredError,
    PostNotFoundError,
)
from app.infrastructure.config.settings import Settings
from app.infrastructure.instagram.error_mapping import DEAD_SESSION
from app.infrastructure.instagram.instagrapi_source import InstagrapiInstagramSource
from app.infrastructure.instagram.session import _handle_exception
from instagrapi.exceptions import (
    BadPassword,
    ClientError,
    ClientLoginRequired,
    LoginRequired,
    MediaNotFound,
    ReloginAttemptExceeded,
)

URL = "https://www.instagram.com/p/DfZ69nZEeFv/"


@pytest.fixture(autouse=True)
def _isolated_guard_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # The adapter persists breaker/budget state and reads the saved session:
    # keep both out of the repo (a real session.json must never be probed).
    monkeypatch.setenv("IG_GUARD_FILE", str(tmp_path / "ig_guard.json"))
    monkeypatch.setenv("IG_SESSION_FILE", str(tmp_path / "session.json"))


def _settings() -> Settings:
    return Settings()


class StubClient:
    """Mimics the parts of instagrapi.Client that get_post / send_dm touch.
    Any login method called on it is recorded (none may be)."""

    def __init__(self, media_error: Exception, private_error: Exception | None = None) -> None:
        self.handle_exception = _handle_exception
        self._media_error = media_error
        self._private_error = private_error
        self.login_calls: list[str] = []

    def __getattr__(self, name: str) -> Any:
        if name in ("login", "relogin", "login_by_sessionid", "totp_generate_code"):
            return lambda *a, **k: self.login_calls.append(name)
        raise AttributeError(name)

    def media_pk_from_url(self, url: str) -> str:
        return "123"

    def media_info(self, media_pk: str) -> Any:
        # instagrapi: a failed private request runs the hook; whatever the hook
        # raises is swallowed and the public path is tried.
        if self._private_error is not None:
            with contextlib.suppress(Exception):  # mirrors instagrapi's broad fallback
                self.handle_exception(self, self._private_error)
        raise self._media_error

    def direct_send(self, text: str, user_ids: list[int]) -> None:
        # instagrapi does not swallow hook errors on sends: they propagate.
        self.handle_exception(self, self._private_error or LoginRequired())


def _source_with(client: object) -> InstagrapiInstagramSource:
    source = InstagrapiInstagramSource(_settings())
    source._client = client
    return source


def test_get_post_dead_session_is_login_required_and_never_relogs() -> None:
    client = StubClient(ClientError("public fallback failed"), private_error=LoginRequired())
    source = _source_with(client)

    with pytest.raises(LoginRequiredError) as info:
        source.get_post(URL)

    assert str(info.value) == DEAD_SESSION
    assert not isinstance(info.value, PostNotFoundError)
    assert client.login_calls == []  # no relogin, no login of any kind
    assert source._client is None  # the dead client is dropped


def test_after_a_dead_session_the_next_operation_never_logs_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.infrastructure.instagram import login

    built: list[object] = []
    monkeypatch.setattr(login, "build_client", lambda *a: built.append(a))
    client = StubClient(ClientError(), private_error=LoginRequired())
    source = _source_with(client)
    with pytest.raises(LoginRequiredError):
        source.get_post(URL)

    with pytest.raises(LoginRequiredError) as again:
        source.get_post(URL)  # no client, no saved session: refused, no request

    assert "pegá tu sessionid desde el chip IG" in str(again.value)
    assert built == []  # no new client, so no request of any kind
    assert client.login_calls == []


def test_env_credentials_and_sessionid_no_longer_log_in(monkeypatch: pytest.MonkeyPatch) -> None:
    """L24: with no saved session, an old IG_SESSIONID / user+password in the
    environment are not used: LoginRequiredError and no client, no request."""
    from app.infrastructure.instagram import login

    for name, value in (
        ("IG_SESSIONID", "abc"),
        ("IG_USERNAME", "u"),
        ("IG_PASSWORD", "p"),
        ("IG_2FA_SECRET", "JBSWY3DPEHPK3PXP"),
    ):
        monkeypatch.setenv(name, value)
    built: list[object] = []
    monkeypatch.setattr(login, "build_client", lambda *a: built.append(a))
    source = InstagrapiInstagramSource(Settings(_env_file=None))

    with pytest.raises(LoginRequiredError) as info:
        source.current_user_pk()

    assert str(info.value) == login.NO_SESSION
    assert built == []


@pytest.mark.parametrize(
    "exc",
    [LoginRequired(), ReloginAttemptExceeded(), ClientLoginRequired()],
    ids=["LoginRequired", "ReloginAttemptExceeded", "ClientLoginRequired"],
)
def test_get_post_maps_session_errors_to_login_required(exc: Exception) -> None:
    source = _source_with(StubClient(exc))

    with pytest.raises(LoginRequiredError) as info:
        source.get_post(URL)

    assert not isinstance(info.value, PostNotFoundError)
    assert source._client is None


def test_hook_never_returns_so_instagrapi_never_resends() -> None:
    """A hook that returns makes instagrapi re-send the request; none may."""
    client = StubClient(ClientError())
    original = LoginRequired()

    with pytest.raises(LoginRequired) as info:
        _handle_exception(client, original)

    assert info.value is original
    assert client.login_calls == []


def test_hook_reraises_non_session_errors_unchanged() -> None:
    client = StubClient(ClientError())
    original = ClientError("throttled")

    with pytest.raises(ClientError) as info:
        _handle_exception(client, original)

    assert info.value is original


# -- previous behaviour that must still hold -------------------------------


def test_get_post_media_not_found_is_post_not_found() -> None:
    client = StubClient(MediaNotFound("gone"))
    source = _source_with(client)

    with pytest.raises(PostNotFoundError):
        source.get_post(URL)

    assert source._client is client  # a missing post is not a session problem


def test_get_post_other_client_error_is_still_post_not_found() -> None:
    client = StubClient(ClientError("not available"))
    source = _source_with(client)

    with pytest.raises(PostNotFoundError):
        source.get_post(URL)

    assert source._client is client


def test_send_dm_ip_block_stays_ip_blocked() -> None:
    blocked = BadPassword("Your IP address is on a blacklist")
    client = StubClient(ClientError(), private_error=blocked)
    source = _source_with(client)

    with pytest.raises(IpBlockedError):
        source.send_dm("5", "hola")

    assert source._client is client  # an IP block is not a dead session


def test_send_dm_dead_session_is_login_error_and_drops_client() -> None:
    client = StubClient(ClientError())
    source = _source_with(client)

    with pytest.raises(LoginRequiredError) as info:
        source.send_dm("5", "hola")

    assert "sessionid" in str(info.value)
    assert client.login_calls == []
    assert source._client is None


# -- L15: every adapter message is Spanish (a failed job shows it as is) -------


def test_challenge_code_message_is_spanish() -> None:
    from app.domain.errors import ChallengeRequiredError
    from app.infrastructure.instagram.guard import IgGuard
    from app.infrastructure.instagram.login import IgLogin

    settings = Settings(_env_file=None)
    login = IgLogin(settings, IgGuard(settings, sleep=lambda _: None))

    with pytest.raises(ChallengeRequiredError) as challenge:
        login._challenge_code_handler("rgb.collective", None)
    assert str(challenge.value) == (
        "Instagram pidió un código de verificación para rgb.collective: "
        "confirmá que sos vos desde el celu y volvé a conectar."
    )


def test_a_missing_post_maps_to_a_spanish_result() -> None:
    from app.application.use_cases import map_instagram_error
    from app.domain.result import Err, ErrorCode

    assert map_instagram_error(PostNotFoundError("https://instagram.com/p/x/")) == Err(
        ErrorCode.POST_NOT_FOUND, "No se encontró el post (borrado, privado o link inválido)."
    )
