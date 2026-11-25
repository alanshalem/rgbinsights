"""S22: the Instagram session flows over HTTP — /ig/status, /ig/reauth,
/ig/sessionid and /ig/disconnect — against a stub source (no Instagram)."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from app.api.deps import instagram_dep, session_dep
from app.bootstrap import InstagramAccess
from app.domain.errors import InstagramError, LoginRequiredError
from app.infrastructure.config.settings import Settings, get_settings
from app.infrastructure.instagram.guard import IgGuard
from app.infrastructure.persistence import db
from app.main import app
from sqlalchemy import Engine
from sqlmodel import Session

from tests.test_jobs_api import _call

START = datetime(2026, 11, 24, 15, 0, tzinfo=UTC)


class StubSource:
    """Counts what the routes ask for; logs in only when asked to."""

    def __init__(self, fail: InstagramError | None = None) -> None:
        self.fail = fail
        self.pk: str | None = None
        self.calls: list[str] = []

    def cached_user_pk(self) -> str | None:
        self.calls.append("cached_user_pk")
        return self.pk

    def current_user_pk(self) -> str:
        self.calls.append("current_user_pk")
        if self.fail is not None:
            raise self.fail
        self.pk = "42"
        return self.pk

    def connect_sessionid(self, sessionid: str) -> str:
        self.calls.append(f"connect_sessionid:{sessionid}")
        if self.fail is not None:
            raise self.fail
        self.pk = "42"
        return self.pk


class Wiring:
    def __init__(self, tmp_path: Path) -> None:
        self.settings = Settings(
            _env_file=None,
            ig_source="instagrapi",
            ig_session_file=str(tmp_path / "session.json"),
            ig_guard_file=str(tmp_path / "ig_guard.json"),
        )
        self.guard = IgGuard(self.settings, clock=lambda: START, sleep=lambda _: None)
        self.built: list[StubSource] = []
        self.next_fail: InstagramError | None = None
        self.access = InstagramAccess(self._build, lambda _: self.guard)

    def _build(self, _settings: Settings) -> Any:
        source = StubSource(self.next_fail)
        self.built.append(source)
        return source


@pytest.fixture
def wiring(tmp_path: Path) -> Iterator[Wiring]:
    engine: Engine = db.build_engine(f"sqlite:///{tmp_path / 'ig.db'}")
    db.create_db_and_tables(engine)
    w = Wiring(tmp_path)

    def session() -> Iterator[Session]:
        with Session(engine) as s:
            yield s

    overrides: dict[Callable[..., Any], Callable[..., Any]] = {
        session_dep: session,
        get_settings: lambda: w.settings,
        instagram_dep: lambda: w.access,
    }
    app.dependency_overrides.update(overrides)
    try:
        yield w
    finally:
        for dep in overrides:
            app.dependency_overrides.pop(dep, None)
        engine.dispose()


def test_status_is_read_only_and_never_logs_in(wiring: Wiring) -> None:
    for _ in range(3):
        status, _, body = _call("GET", "/ig/status")
        assert status == 200
    assert body["state"] == "disconnected"
    assert body["demo"] is False and body["source"] == "instagrapi"
    assert len(wiring.built) == 1  # the shared source, built once
    assert wiring.built[0].calls == ["cached_user_pk"] * 3  # no login, no Instagram


def test_reauth_drops_the_cached_session_and_logs_in_once(wiring: Wiring) -> None:
    _call("GET", "/ig/status")
    status, _, body = _call("POST", "/ig/reauth")

    assert status == 200
    assert body["state"] == "connected" and body["pk"] == "42"
    assert len(wiring.built) == 2  # a fresh source after the reset
    assert wiring.built[1].calls == ["current_user_pk", "cached_user_pk"]
    _, _, again = _call("GET", "/ig/status")
    assert again["state"] == "connected"  # the new session is the shared one now
    assert len(wiring.built) == 2


def test_reauth_failure_is_the_mapped_http_error(wiring: Wiring) -> None:
    wiring.next_fail = LoginRequiredError("La sesión venció.")
    status, _, body = _call("POST", "/ig/reauth")
    assert status == 401
    assert body == {"detail": {"code": "login_required", "message": "La sesión venció."}}
    assert wiring.built[-1].calls == ["current_user_pk"]  # one attempt, no retry


def test_sessionid_connects_with_one_call(wiring: Wiring) -> None:
    status, _, body = _call("POST", "/ig/sessionid", body={"sessionid": "  fresh  "})
    assert status == 200
    assert body["state"] == "connected" and body["pk"] == "42"
    assert wiring.built[0].calls == ["connect_sessionid:fresh", "cached_user_pk"]


def test_blank_sessionid_is_400_and_touches_nothing(wiring: Wiring) -> None:
    status, _, body = _call("POST", "/ig/sessionid", body={"sessionid": "   "})
    assert status == 400
    assert body == {"detail": {"code": "bad_request", "message": "sessionid vacío"}}
    assert wiring.built == []


def test_disconnect_forgets_the_session_without_calling_instagram(wiring: Wiring) -> None:
    _call("POST", "/ig/reauth")
    session_file = Path(wiring.settings.ig_session_file)
    session_file.write_text("{}", encoding="utf-8")
    calls_before = list(wiring.built[-1].calls)
    built_before = len(wiring.built)

    status, _, body = _call("POST", "/ig/disconnect")

    assert status == 200
    assert body["state"] == "disconnected" and body["pk"] is None
    assert not session_file.exists()
    assert wiring.built[-1].calls == calls_before  # nothing asked of Instagram
    _, _, after = _call("GET", "/ig/status")
    assert after["state"] == "disconnected"  # a fresh source: the old client is gone
    assert len(wiring.built) == built_before + 1
