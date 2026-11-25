"""Fase 0 anti-ban rails (S1, S2, S4, S5, S7).

No network: HTTP is stubbed under a real ``requests.Session`` (the guard wraps
``Session.request``, the single choke point every instagrapi call goes through),
and login flows use stub clients. State files live in pytest's tmp_path.
"""

from __future__ import annotations

import random
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import requests
from app import bootstrap
from app.api.routers import avatars, ig
from app.api.schemas import IgSessionIdIn
from app.bootstrap import InstagramAccess
from app.domain.errors import (
    BudgetExhaustedError,
    ChallengeRequiredError,
    IgBusyError,
    IpBlockedError,
    LoginRequiredError,
    RateLimitedError,
    SendBlockedError,
    SendRetryableError,
)
from app.infrastructure.config.settings import Settings
from app.infrastructure.instagram import login
from app.infrastructure.instagram.guard import IgGuard
from app.infrastructure.instagram.instagrapi_source import InstagrapiInstagramSource
from app.infrastructure.instagram.session import build_client
from app.infrastructure.instagram.throttle import HumanPacer
from app.infrastructure.persistence import models
from fastapi import HTTPException
from instagrapi.exceptions import (
    ChallengeRequired,
    ClientBadRequestError,
    ClientConnectionError,
    ClientForbiddenError,
    LoginRequired,
)
from sqlmodel import Session

START = datetime(2026, 11, 24, 15, 0, tzinfo=UTC)  # 12:00 in Argentina
URL = "https://i.instagram.com/api/v1/feed/test/"


class Clock:
    def __init__(self, now: datetime = START) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta: float) -> None:
        self.now += timedelta(**delta)


class FakeHttp(requests.adapters.BaseAdapter):
    """Stands in for the network: a transport adapter mounted under a real
    requests.Session, so requests' own redirect handling runs on top of it."""

    def __init__(self, *responses: tuple[Any, ...]) -> None:
        super().__init__()
        self.calls: list[str] = []
        self._responses = list(responses)
        self.repeat_last = False

    def send(self, request: Any, *args: Any, **kwargs: Any) -> requests.Response:
        url = str(request.url)
        self.calls.append(url)
        if not self._responses:
            spec: tuple[Any, ...] = (200, "{}")
        elif self.repeat_last and len(self._responses) == 1:
            spec = self._responses[0]
        else:
            spec = self._responses.pop(0)
        resp = requests.Response()
        resp.status_code = spec[0]
        resp._content = spec[1].encode()
        resp.headers.update(spec[2] if len(spec) > 2 else {})
        resp.url = url
        resp.request = request
        return resp

    def close(self) -> None:
        pass


def _session(http: FakeHttp) -> requests.Session:
    session = requests.Session()
    session.mount("https://", http)
    session.mount("http://", http)
    return session


def _settings(tmp_path: Path, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "use_fake_instagram": False,
        "ig_source": "instagrapi",
        "ig_guard_file": str(tmp_path / "ig_guard.json"),
        "ig_session_file": str(tmp_path / "session.json"),
        "ig_sessionid": "",
        "ig_username": "",
        "ig_password": "",
        "ig_proxy": "",
        "scan_min_delay_seconds": 2.0,
        "scan_max_delay_seconds": 6.0,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def _guard(
    tmp_path: Path, clock: Clock | None = None, sleeps: list[float] | None = None, **overrides: Any
) -> IgGuard:
    record = sleeps if sleeps is not None else []
    return IgGuard(
        _settings(tmp_path, **overrides),
        clock=clock or Clock(),
        sleep=record.append,
        rng=random.Random(7),
    )


def _client(http: FakeHttp) -> Any:
    return SimpleNamespace(private=_session(http), public=None, delay_range=[1, 3])


# -- S5: real per-hour / per-day budget ----------------------------------------


def test_budget_counts_every_http_request_and_survives_restart(tmp_path: Path) -> None:
    http = FakeHttp()
    guard = _guard(tmp_path, ig_max_requests_per_hour=3)
    client = _client(http)
    guard.install(client)

    for _ in range(3):  # three pages of a paginated read = three requests
        client.private.get(URL)
    with pytest.raises(RateLimitedError) as info:
        client.private.get(URL)

    assert len(http.calls) == 3  # the 4th never reached the network
    assert "por hora" in str(info.value)
    assert "13:00" in str(info.value)  # resumes at the next AR hour

    restarted = _guard(tmp_path, ig_max_requests_per_hour=3)  # same state file
    fresh = _client(http)
    restarted.install(fresh)
    with pytest.raises(RateLimitedError):
        fresh.private.get(URL)
    assert len(http.calls) == 3


def test_budget_hour_window_rolls_but_day_cap_holds(tmp_path: Path) -> None:
    http = FakeHttp()
    clock = Clock()
    guard = _guard(tmp_path, clock, ig_max_requests_per_hour=2, ig_max_requests_per_day=3)
    client = _client(http)
    guard.install(client)

    client.private.get(URL)
    client.private.get(URL)
    clock.advance(hours=1)
    client.private.get(URL)  # new hour, still under the day cap
    with pytest.raises(RateLimitedError) as info:
        client.private.get(URL)

    assert len(http.calls) == 3
    assert "por día" in str(info.value)


@pytest.mark.parametrize(
    "response",
    [
        (429, "Too Many Requests"),
        (400, '{"message": "feedback_required", "status": "fail"}'),
        (400, '{"message": "Please wait a few minutes before you try again."}'),
    ],
    ids=["429", "feedback_required", "please_wait"],
)
def test_throttle_response_starts_persisted_cooldown(
    tmp_path: Path, response: tuple[int, str]
) -> None:
    http = FakeHttp(response)
    clock = Clock()
    guard = _guard(tmp_path, clock, ig_throttle_cooldown_minutes=60)
    client = _client(http)
    guard.install(client)

    client.private.get(URL)  # instagrapi turns the response into its own exception
    with pytest.raises(RateLimitedError) as info:
        client.private.get(URL)

    assert len(http.calls) == 1  # everything stops: no request during the cooldown
    assert "13:00" in str(info.value)  # 12:00 AR + 60 min
    assert guard.snapshot().blocked_until == START + timedelta(minutes=60)

    restarted = _guard(tmp_path, clock, ig_throttle_cooldown_minutes=60)
    assert restarted.snapshot().blocked_until == START + timedelta(minutes=60)

    clock.advance(minutes=61)
    client.private.get(URL)
    assert len(http.calls) == 2


def test_build_client_routes_requests_through_the_guard(tmp_path: Path) -> None:
    settings = _settings(tmp_path, ig_max_requests_per_hour=0)
    client = build_client(settings, lambda *_: "")

    # A local, closed port: even unguarded this never reaches Instagram.
    with pytest.raises(RateLimitedError):
        client.private.get("http://127.0.0.1:9/")
    assert client.delay_range is None  # pacing is central, not instagrapi's uniform 1-3 s


# -- S7: human pacing ----------------------------------------------------------


def test_pacer_is_jittered_bounded_and_never_faster_than_before() -> None:
    pacer = HumanPacer(2.0, 6.0, rest_every=10, rest_min=45.0, rest_max=150.0, rng=random.Random(1))
    delays = [pacer.next_delay() for _ in range(1000)]

    rests = delays[9::10]
    normal = [d for i, d in enumerate(delays) if (i + 1) % 10]
    assert all(d >= 2.0 for d in delays)
    assert max(delays) <= 6.0 * 4 + 150.0  # bounded
    assert all(r >= 45.0 for r in rests)  # a long rest every N requests
    assert sum(normal) / len(normal) >= 4.0  # mean >= the old uniform(min, max) midpoint
    assert len({round(d, 1) for d in normal}) > 30  # jittered, not a fixed beat


def test_guard_paces_before_every_request(tmp_path: Path) -> None:
    sleeps: list[float] = []
    guard = _guard(tmp_path, sleeps=sleeps)
    client = _client(FakeHttp())
    guard.install(client)

    for _ in range(3):
        client.private.get(URL)

    assert len(sleeps) == 3
    assert all(s >= 2.0 for s in sleeps)


def test_avatar_download_looks_like_a_browser_and_uses_ig_proxy(
    tmp_path: Path, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, Any]] = []

    def fake_get(url: str, **kwargs: Any) -> requests.Response:
        calls.append({"url": url, **kwargs})
        resp = requests.Response()
        resp.status_code = 200
        resp._content = b"jpeg"
        resp.headers["content-type"] = "image/jpeg"
        return resp

    monkeypatch.setattr(avatars, "_CACHE_DIR", tmp_path)
    monkeypatch.setattr(requests, "get", fake_get)
    session.add(
        models.User(
            pk="77",
            username="lucia",
            profile_pic_url="https://scontent.cdninstagram.com/pic.jpg",
            first_seen_at=START,
            last_seen_at=START,
        )
    )
    session.commit()
    proxy = "http://u:p@proxy.local:8080"

    avatars.avatar("77", session=session, settings=_settings(tmp_path, ig_proxy=proxy))
    avatars.avatar("77", session=session, settings=_settings(tmp_path, ig_proxy=proxy))

    assert len(calls) == 1  # second hit served from the disk cache
    assert "Mozilla/5.0" in calls[0]["headers"]["User-Agent"]
    assert calls[0]["proxies"] == {"http": proxy, "https": proxy}
    assert (tmp_path / "77.jpg").read_bytes() == b"jpeg"


# -- S4: one Instagram operation at a time ------------------------------------


class SlowClient:
    """Stub instagrapi client that records how many calls overlap."""

    def __init__(self) -> None:
        self.user_id = 1
        self.active = 0
        self.max_active = 0
        self.calls = 0

    def _work(self) -> None:
        self.calls += 1
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        time.sleep(0.05)
        self.active -= 1

    def user_info_by_username(self, username: str) -> Any:
        self._work()
        return SimpleNamespace(
            pk=2,
            username=username,
            full_name="",
            follower_count=1,
            is_verified=False,
            is_business=False,
            biography="",
            is_private=False,
            profile_pic_url=None,
        )

    def direct_send(self, text: str, user_ids: list[int]) -> None:
        self._work()


def test_campaign_send_and_request_reads_never_overlap(tmp_path: Path) -> None:
    source = InstagrapiInstagramSource(_settings(tmp_path), guard=_guard(tmp_path))
    client = SlowClient()
    source._client = client

    def reads() -> None:
        for _ in range(3):
            source.get_profile("lucia")

    def sends() -> None:
        for _ in range(3):
            source.send_dm("5", "hola")

    threads = [threading.Thread(target=reads), threading.Thread(target=sends)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(5)

    assert not any(t.is_alive() for t in threads)
    assert client.calls == 6  # every read and every send ran...
    assert client.max_active == 1  # ...one at a time


def test_nested_operations_do_not_deadlock(tmp_path: Path) -> None:
    guard = _guard(tmp_path)
    done = threading.Event()

    def nested() -> None:
        with guard.operation(), guard.operation():
            done.set()

    worker = threading.Thread(target=nested)
    worker.start()
    worker.join(2)
    assert done.is_set()


def test_busy_lock_waits_bounded_then_fails_fast(tmp_path: Path) -> None:
    guard = _guard(tmp_path, ig_lock_wait_seconds=0.05)
    holding = threading.Event()
    release = threading.Event()

    def hold() -> None:
        with guard.operation():
            holding.set()
            release.wait(2)

    worker = threading.Thread(target=hold)
    worker.start()
    holding.wait(2)
    try:
        with pytest.raises(IgBusyError) as info, guard.operation():
            pass
    finally:
        release.set()
        worker.join(2)
    assert "ocupado" in str(info.value)


# -- S2: login circuit breaker -------------------------------------------------


class LoginStub:
    """A fresh instagrapi client whose login makes one (stubbed) request."""

    def __init__(self, http: FakeHttp, fail: Exception | None) -> None:
        self.private = _session(http)
        self.public = None
        self.delay_range = None
        self.user_id = 42
        self._fail = fail
        self.dumped = 0

    def login_by_sessionid(self, sessionid: str) -> bool:
        self.private.get(URL)
        if self._fail is not None:
            raise self._fail
        return True

    def account_info(self) -> Any:
        self.private.get(URL)
        return SimpleNamespace(pk=42)

    def dump_settings(self, path: Path) -> None:
        self.dumped += 1


class LoginFactory:
    """Replaces build_client: counts login attempts, installs the test guard."""

    def __init__(self, guard: IgGuard, http: FakeHttp) -> None:
        self.guard = guard
        self.http = http
        self.fail: Exception | None = LoginRequired("sessionid dead")
        self.built: list[LoginStub] = []

    def __call__(self, settings: Settings, handler: Any) -> LoginStub:
        client = LoginStub(self.http, self.fail)
        self.guard.install(client)
        self.built.append(client)
        return client


def _login_setup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: Clock
) -> tuple[InstagrapiInstagramSource, IgGuard, LoginFactory]:
    settings = _settings(tmp_path, ig_sessionid="abc")
    guard = IgGuard(settings, clock=clock, sleep=lambda _: None, rng=random.Random(3))
    factory = LoginFactory(guard, FakeHttp())
    monkeypatch.setattr(login, "build_client", factory)
    return InstagrapiInstagramSource(settings, guard=guard), guard, factory


def test_failed_login_opens_escalating_persisted_breaker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = Clock()
    source, guard, factory = _login_setup(tmp_path, monkeypatch, clock)

    expected = [timedelta(minutes=15), timedelta(hours=1), timedelta(hours=6), timedelta(hours=6)]
    for step in expected:
        with pytest.raises(LoginRequiredError):
            source.current_user_pk()
        attempts = len(factory.built)
        assert guard.snapshot().blocked_until == clock.now + step

        # While open: fail fast, say until when, never attempt a login.
        with pytest.raises(LoginRequiredError) as info:
            source.current_user_pk()
        assert len(factory.built) == attempts
        assert "hasta las" in str(info.value)
        clock.advance(seconds=step.total_seconds() + 1)

    clock.now -= timedelta(seconds=2)  # back inside the last window
    restarted = IgGuard(_settings(tmp_path), clock=clock, sleep=lambda _: None)
    assert restarted.snapshot().blocked_until is not None


def test_successful_login_resets_breaker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    clock = Clock()
    source, guard, factory = _login_setup(tmp_path, monkeypatch, clock)
    with pytest.raises(LoginRequiredError):
        source.current_user_pk()
    clock.advance(minutes=16)

    factory.fail = None
    assert source.current_user_pk() == "42"
    assert guard.snapshot().blocked_until is None

    source._client = None  # session died again
    factory.fail = LoginRequired("dead again")
    with pytest.raises(LoginRequiredError):
        source.current_user_pk()
    assert guard.snapshot().blocked_until == clock.now + timedelta(minutes=15)  # back to step 1


def test_fresh_sessionid_may_bypass_an_open_login_breaker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = Clock()
    source, guard, factory = _login_setup(tmp_path, monkeypatch, clock)
    with pytest.raises(LoginRequiredError):
        source.current_user_pk()

    factory.fail = None
    assert source.connect_sessionid("fresh") == "42"
    assert factory.built[-1].dumped == 1  # persisted to session.json
    assert guard.snapshot().blocked_until is None
    assert source.cached_user_pk() == "42"


def test_ip_block_breaker_is_not_bypassed_by_a_sessionid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = Clock()
    source, guard, factory = _login_setup(tmp_path, monkeypatch, clock)
    factory.fail = Exception("Your IP address is on a blacklist")
    with pytest.raises(IpBlockedError):
        source.current_user_pk()
    attempts = len(factory.built)

    factory.fail = None
    with pytest.raises(IpBlockedError) as info:
        source.connect_sessionid("fresh")
    assert len(factory.built) == attempts  # no request at all
    assert "hasta las" in str(info.value)


def test_login_without_any_request_does_not_open_breaker(tmp_path: Path) -> None:
    guard = _guard(tmp_path)
    source = InstagrapiInstagramSource(_settings(tmp_path), guard=guard)  # no creds at all

    with pytest.raises(LoginRequiredError):
        source.current_user_pk()
    assert guard.snapshot().blocked_until is None  # nothing hit Instagram


def test_send_dm_surfaces_cooldown_instead_of_a_retryable_failure(tmp_path: Path) -> None:
    http = FakeHttp((429, "Too Many Requests"))
    guard = _guard(tmp_path)
    client = _client(http)
    guard.install(client)
    client.private.get(URL)  # trips the cooldown

    sent: list[str] = []
    stub = SimpleNamespace(
        user_id=1,
        direct_send=lambda text, user_ids: sent.append(client.private.get(URL).url),
    )
    source = InstagrapiInstagramSource(_settings(tmp_path), guard=guard)
    source._client = stub

    with pytest.raises(RateLimitedError) as info:
        source.send_dm("5", "hola")
    assert "hasta las" in str(info.value)
    assert len(http.calls) == 1


# -- S1: /ig/status never logs in ---------------------------------------------


def _status_setup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Settings, InstagrapiInstagramSource, IgGuard, list[int]]:
    settings = _settings(tmp_path, ig_sessionid="abc", ig_username="u", ig_password="p")
    guard = IgGuard(settings, clock=Clock(), sleep=lambda _: None)
    source = InstagrapiInstagramSource(settings, guard=guard)
    logins: list[int] = []

    def no_login(*_: Any) -> Any:
        logins.append(1)
        raise AssertionError("status must not log in")

    monkeypatch.setattr(login, "build_client", no_login)
    monkeypatch.setattr(bootstrap, "instagram", InstagramAccess(lambda _: source, lambda _: guard))
    return settings, source, guard, logins


def test_status_never_logs_in(
    tmp_path: Path, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, _, _, logins = _status_setup(tmp_path, monkeypatch)

    for _ in range(3):  # the UI polls every 20 s
        out = ig.ig_status(session=session, settings=settings, instagram=bootstrap.instagram)

    assert logins == []
    assert out.state == "disconnected"
    assert out.cooldown_until is None


def test_status_reports_open_breaker(
    tmp_path: Path, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, source, guard, _ = _status_setup(tmp_path, monkeypatch)
    http = FakeHttp()
    client = _client(http)
    guard.install(client)
    with pytest.raises(LoginRequiredError), guard.operation():
        client.private.get(URL)
        raise LoginRequiredError("La sesión venció.")

    out = ig.ig_status(session=session, settings=settings, instagram=bootstrap.instagram)

    assert out.state == "disconnected"
    assert out.cooldown_until == START + timedelta(minutes=15)
    assert out.last_error is not None and "La sesión venció." in out.last_error


def test_status_connected_from_the_in_memory_client(
    tmp_path: Path, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, source, _, logins = _status_setup(tmp_path, monkeypatch)
    source._client = SimpleNamespace(user_id=42)

    out = ig.ig_status(session=session, settings=settings, instagram=bootstrap.instagram)

    assert out.state == "connected"
    assert out.pk == "42"
    assert logins == []


def test_sessionid_endpoint_connects_with_a_single_probe(
    tmp_path: Path, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    guard = IgGuard(settings, clock=Clock(), sleep=lambda _: None)
    http = FakeHttp()
    factory = LoginFactory(guard, http)
    factory.fail = None
    source = InstagrapiInstagramSource(settings, guard=guard)
    monkeypatch.setattr(login, "build_client", factory)
    monkeypatch.setattr(bootstrap, "instagram", InstagramAccess(lambda _: source, lambda _: guard))

    out = ig.ig_set_sessionid(
        IgSessionIdIn(sessionid="fresh"),
        session=session,
        settings=settings,
        instagram=bootstrap.instagram,
    )

    assert out.state == "connected"
    assert out.pk == "42"
    assert len(http.calls) == 2  # login_by_sessionid + one account_info probe, no re-login
    assert out.last_ok_at is not None


# -- B1 (S3): account-level failures on a send are never per-target --------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (ChallengeRequired("challenge_required"), ChallengeRequiredError),
        (ClientBadRequestError("400 checkpoint_required"), ChallengeRequiredError),
        (LoginRequired("login_required"), LoginRequiredError),
    ],
    ids=["challenge", "checkpoint", "login"],
)
def test_send_dm_session_failure_is_not_a_per_target_failure(
    tmp_path: Path, raw: Exception, expected: type[Exception]
) -> None:
    def boom(*args: Any, **kwargs: Any) -> None:
        raise raw

    source = InstagrapiInstagramSource(_settings(tmp_path), guard=_guard(tmp_path))
    source._client = SimpleNamespace(direct_send=boom, user_id=1)

    with pytest.raises(expected):
        source.send_dm("123", "hola")
    assert source._client is None  # the challenged/dead session is not reused


def test_send_dm_forbidden_stops_as_send_blocked(tmp_path: Path) -> None:
    def boom(*args: Any, **kwargs: Any) -> None:
        raise ClientForbiddenError("403 Client Error: Forbidden")

    source = InstagrapiInstagramSource(_settings(tmp_path), guard=_guard(tmp_path))
    source._client = SimpleNamespace(direct_send=boom, user_id=1)

    with pytest.raises(SendBlockedError):
        source.send_dm("123", "hola")


def test_send_dm_network_error_stays_retryable(tmp_path: Path) -> None:
    def boom(*args: Any, **kwargs: Any) -> None:
        raise ClientConnectionError("ConnectionError read timed out")

    source = InstagrapiInstagramSource(_settings(tmp_path), guard=_guard(tmp_path))
    client = SimpleNamespace(direct_send=boom, user_id=1)
    source._client = client

    with pytest.raises(SendRetryableError):
        source.send_dm("123", "hola")
    assert source._client is client


# -- B2 (S2): a malformed state file never takes the guard down -----------------


@pytest.mark.parametrize(
    "content",
    [
        "null",
        "[]",
        '"x"',
        '{"budget": []}',
        '{"breaker_failures": "x"}',
        '{"budget": {"hour_count": "z"}}',
        '{"last_error": ["x"], "breaker_until": 5}',
    ],
)
def test_corrupt_guard_file_starts_clean(tmp_path: Path, content: str) -> None:
    (tmp_path / "ig_guard.json").write_text(content, encoding="utf-8")

    guard = _guard(tmp_path)
    snap = guard.snapshot()

    assert snap.blocked_until is None and not snap.breaker_open
    assert snap.last_error is None
    client = _client(FakeHttp())
    guard.install(client)
    client.private.get(URL)  # still usable


# -- A1 (S5/S7): redirect hops are requests too ---------------------------------


def test_redirect_hops_are_counted_and_paced(tmp_path: Path) -> None:
    http = FakeHttp(
        (302, "", {"Location": URL + "a"}),
        (302, "", {"Location": URL + "b"}),
        (200, "{}"),
    )
    sleeps: list[float] = []
    guard = _guard(tmp_path, sleeps=sleeps, ig_max_requests_per_hour=2)
    client = _client(http)
    guard.install(client)

    with pytest.raises(RateLimitedError):
        client.private.get(URL)

    assert len(http.calls) == 2  # the third hop would exceed the budget
    assert len(sleeps) == 2  # every hop is paced


def test_redirect_chains_are_capped(tmp_path: Path) -> None:
    http = FakeHttp((302, "", {"Location": URL}))
    http.repeat_last = True
    guard = _guard(tmp_path)
    client = _client(http)
    guard.install(client)

    with pytest.raises(requests.TooManyRedirects):
        client.private.get(URL)

    assert len(http.calls) <= 4  # not requests' default of 30 hops


# -- L10 advisories ---------------------------------------------------------------


def test_spent_budget_is_a_budget_error_with_its_reopening_time(tmp_path: Path) -> None:
    guard = _guard(tmp_path, ig_max_requests_per_hour=1)
    client = _client(FakeHttp())
    guard.install(client)
    client.private.get(URL)

    with pytest.raises(BudgetExhaustedError) as info:
        client.private.get(URL)

    assert info.value.retry_at == datetime(2026, 11, 24, 16, 0, tzinfo=UTC)  # 13:00 AR
    assert "13:00" in str(info.value)


def test_instagram_cooldown_is_not_a_budget_error(tmp_path: Path) -> None:
    guard = _guard(tmp_path)
    client = _client(FakeHttp((429, "Too Many Requests")))
    guard.install(client)
    client.private.get(URL)

    with pytest.raises(RateLimitedError) as info:
        client.private.get(URL)
    assert not isinstance(info.value, BudgetExhaustedError)


def test_last_error_clears_after_a_successful_operation_once_recovered(tmp_path: Path) -> None:
    clock = Clock()
    guard = _guard(tmp_path, clock, ig_throttle_cooldown_minutes=60)
    client = _client(FakeHttp((200, "{}"), (429, "Too Many Requests")))
    guard.install(client)
    with guard.operation():  # instagrapi swallowed the 429: the operation "succeeds"
        client.private.get(URL)
        client.private.get(URL)
    assert guard.snapshot().last_error is not None  # still cooling down: keep the reason

    clock.advance(minutes=61)
    with guard.operation():
        client.private.get(URL)

    assert guard.snapshot().last_error is None
    assert _guard(tmp_path, clock).snapshot().last_error is None  # persisted


def test_failed_operation_keeps_last_error(tmp_path: Path) -> None:
    clock = Clock()
    guard = _guard(tmp_path, clock)
    client = _client(FakeHttp((429, "Too Many Requests")))
    guard.install(client)
    client.private.get(URL)
    clock.advance(minutes=61)

    with pytest.raises(RuntimeError), guard.operation():
        raise RuntimeError("no request reached Instagram")

    assert guard.snapshot().last_error is not None


def _avatar_user(session: Session) -> None:
    session.add(
        models.User(
            pk="78",
            username="tomas",
            profile_pic_url="https://scontent.cdninstagram.com/dead.jpg",
            first_seen_at=START,
            last_seen_at=START,
        )
    )
    session.commit()


def test_avatar_failure_is_remembered_and_uses_a_short_timeout(
    tmp_path: Path, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, Any]] = []

    def dead_proxy(url: str, **kwargs: Any) -> requests.Response:
        calls.append(kwargs)
        raise requests.ConnectTimeout("proxy unreachable")

    now = [1000.0]
    monkeypatch.setattr(avatars, "_CACHE_DIR", tmp_path)
    monkeypatch.setattr(avatars, "_failed", {})
    monkeypatch.setattr(time, "monotonic", lambda: now[0])
    monkeypatch.setattr(requests, "get", dead_proxy)
    _avatar_user(session)
    settings = _settings(tmp_path)

    for _ in range(3):
        with pytest.raises(HTTPException) as info:
            avatars.avatar("78", session=session, settings=settings)
        assert info.value.status_code == 404

    assert len(calls) == 1  # the failure is cached: no new download attempt
    assert calls[0]["timeout"] == avatars._TIMEOUT_SECONDS == 4

    now[0] += avatars._FAILURE_TTL_SECONDS + 1
    with pytest.raises(HTTPException):
        avatars.avatar("78", session=session, settings=settings)
    assert len(calls) == 2  # retried once the negative cache expired


def test_same_failed_sessionid_does_not_bypass_the_breaker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = Clock()
    source, guard, factory = _login_setup(tmp_path, monkeypatch, clock)

    with pytest.raises(LoginRequiredError):
        source.connect_sessionid("bad-cookie")
    attempts = len(factory.built)

    factory.fail = None  # it would not matter: nothing may reach Instagram
    with pytest.raises(LoginRequiredError) as info:
        source.connect_sessionid("bad-cookie")
    assert len(factory.built) == attempts
    assert "hasta las" in str(info.value)

    assert source.connect_sessionid("new-cookie") == "42"  # a different one may try


def test_env_sessionid_that_failed_is_not_a_fresh_paste(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = Clock()
    source, _, factory = _login_setup(tmp_path, monkeypatch, clock)  # IG_SESSIONID=abc
    with pytest.raises(LoginRequiredError):
        source.current_user_pk()
    attempts = len(factory.built)

    with pytest.raises(LoginRequiredError):
        source.connect_sessionid(" abc ".strip())
    assert len(factory.built) == attempts


def test_guard_file_stores_only_a_hash_of_the_failed_sessionid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, _, _ = _login_setup(tmp_path, monkeypatch, Clock())
    with pytest.raises(LoginRequiredError):
        source.connect_sessionid("secret-cookie-value")

    saved = (tmp_path / "ig_guard.json").read_text(encoding="utf-8")
    assert "secret-cookie-value" not in saved
    assert '"breaker_sessionid_hash": "' in saved
