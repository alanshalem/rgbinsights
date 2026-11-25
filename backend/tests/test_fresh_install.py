"""L25: a fresh install starts on the real account, and with no saved session it
never touches Instagram — every action answers a clear Spanish "pegá tu sesión".

The real adapter and its guard run here; only `build_client` (the one way to get
an instagrapi client, without which no request can exist) is replaced by a
recorder that fails the test if it is ever called.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import requests
from app.api.deps import (
    campaign_sender_dep,
    instagram_dep,
    runtime_config_dep,
    session_dep,
    session_factory_dep,
)
from app.application.campaign_sender import CampaignSender
from app.application.runtime_config import RuntimeConfigService
from app.bootstrap import InstagramAccess
from app.infrastructure.config.settings import Settings, get_settings
from app.infrastructure.instagram import login
from app.infrastructure.instagram.guard import IgGuard
from app.infrastructure.instagram.instagrapi_source import InstagrapiInstagramSource
from app.infrastructure.persistence import db, models
from app.infrastructure.persistence.campaigns import SqlCampaignStore
from app.infrastructure.persistence.config_store import SqlConfigStore
from app.main import app
from sqlmodel import Session, select

from tests.test_jobs_api import _call, _job_result, _wait_idle

PASTE_HINT = "pegá tu sessionid desde el chip IG"


class Fresh:
    def __init__(self, tmp_path: Path) -> None:
        # Nothing set anywhere: no saved session (the real account, L25/L27).
        self.settings = Settings(
            _env_file=None,
            ig_session_file=str(tmp_path / "session.json"),
            ig_guard_file=str(tmp_path / "ig_guard.json"),
        )
        self.built: list[Any] = []
        self.engine = db.build_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
        db.create_db_and_tables(self.engine)
        self.runtime = RuntimeConfigService(
            SqlConfigStore(lambda: Session(self.engine)), self.settings.runtime_defaults
        )
        self.runtime.load()
        self.guard = IgGuard(self.settings, config=self.runtime.current, sleep=lambda _: None)
        self.access = InstagramAccess(
            lambda s: InstagrapiInstagramSource(s, self.guard, self.runtime.current),
            lambda _: self.guard,
        )


@pytest.fixture
def fresh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Fresh]:
    f = Fresh(tmp_path)

    def no_client(*args: Any) -> Any:
        f.built.append(args)
        raise AssertionError("no Instagram client may be built without a saved session")

    monkeypatch.setattr(login, "build_client", no_client)

    def session() -> Iterator[Session]:
        with Session(f.engine) as s:
            yield s

    overrides: dict[Callable[..., Any], Callable[..., Any]] = {
        session_dep: session,
        session_factory_dep: lambda: lambda: Session(f.engine),
        get_settings: lambda: f.settings,
        runtime_config_dep: lambda: f.runtime,
        instagram_dep: lambda: f.access,
    }
    app.dependency_overrides.update(overrides)
    try:
        yield f
    finally:
        _wait_idle()
        for dep in overrides:
            app.dependency_overrides.pop(dep, None)
        f.engine.dispose()


def _no_instagram(f: Fresh) -> None:
    assert f.built == []  # no client, so not a single HTTP request
    snap = f.guard.snapshot()
    assert (snap.blocked_until, snap.last_error) == (None, None)  # no attempt, no breaker
    assert f.guard._budget.day_count == 0


def test_the_app_always_uses_the_real_account(fresh: Fresh) -> None:
    _, _, config = _call("GET", "/config")
    _, _, health = _call("GET", "/health")

    assert all(e["key"] != "ig_source" for e in config["entries"])  # L27: no mode setting
    assert health == {"status": "ok", "using_fake_instagram": False}


def test_fresh_install_status_scan_and_sync_never_touch_instagram(fresh: Fresh) -> None:
    status, _, ig = _call("GET", "/ig/status")
    assert status == 200
    assert (ig["state"], ig["demo"], ig["source"], ig["has_saved_session"]) == (
        "disconnected",
        False,
        "instagrapi",
        False,
    )

    status, _, body = _call(
        "POST",
        "/events",
        body={
            "name": "F",
            "promo_start": "2026-06-01T00:00:00+00:00",
            "event_date": "2026-06-30T00:00:00+00:00",
        },
    )
    assert status == 200
    scan = _job_result(
        "POST", "/scan/posts", "scan", body={"urls": ["https://instagram.com/p/Cabc123/"]}
    )
    sync = _job_result("POST", "/sync/dms", "sync")
    refresh = _job_result("POST", f"/events/{body['id']}/refresh", "refresh")

    for job in (scan, sync, refresh):
        assert job["status"] == "error"
        assert job["error_code"] == "login_required"
        assert job["error"] == login.NO_SESSION
        assert PASTE_HINT in job["error"]

    status, _, reauth = _call("POST", "/ig/reauth")
    assert status == 401
    assert reauth == {"detail": {"code": "login_required", "message": login.NO_SESSION}}

    _, _, after = _call("GET", "/ig/status")
    assert after["state"] == "disconnected" and after["last_error"] is None
    _no_instagram(fresh)


# -- L29: every action of a fresh install, with the network itself refusing ----------


def _seed_red(f: Fresh) -> int:
    """A fiesta with one never-scanned post liked by one red user (no DM)."""
    now = datetime.now(UTC)
    with Session(f.engine) as s:
        event = models.Event(name="F", promo_start=now, event_date=now, created_at=now)
        s.add(event)
        s.commit()
        assert event.id is not None
        s.add(models.User(pk="501", username="fan", first_seen_at=now, last_seen_at=now))
        s.add(
            models.Post(
                media_pk="5", shortcode="C5", url="https://instagram.com/p/C5/", event_id=event.id
            )
        )
        s.commit()
        s.add(models.Engagement(user_pk="501", post_media_pk="5", type="like"))
        s.commit()
        return event.id


CAMPAIGN = {
    "delay_min": 60,
    "delay_max": 120,
    "daily_cap": 10,
    "hour_start": 0,
    "hour_end": 24,
    "templates": ["hola {nombre}"],
}


def test_fresh_install_every_action_sends_nothing(
    fresh: Fresh, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[object] = []

    def refuse(self: object, request: object, **kwargs: object) -> object:
        sent.append(request)
        raise AssertionError("no HTTP request may leave the app")

    monkeypatch.setattr(requests.Session, "send", refuse)
    sender = CampaignSender(
        SqlCampaignStore(lambda: Session(fresh.engine)),
        fresh.access.source,
        fresh.settings.local_tz(),
        lambda *args: None,
    )
    app.dependency_overrides[campaign_sender_dep] = lambda: sender
    try:
        event_id = _seed_red(fresh)
        rescan = _job_result("POST", f"/events/{event_id}/rescan", "rescan")
        enrich = _job_result("POST", f"/events/{event_id}/enrich", "enrich")
        status, _, test_send = _call("POST", f"/events/{event_id}/campaign/test", body=CAMPAIGN)
        created, _, campaign = _call("POST", f"/events/{event_id}/campaign", body=CAMPAIGN)
        assert created == 200, campaign
        deadline = time.monotonic() + 10
        while _status(fresh, campaign["id"]) == "running":
            assert time.monotonic() < deadline, "the campaign never stopped"
            time.sleep(0.02)
    finally:
        app.dependency_overrides.pop(campaign_sender_dep, None)

    for job in (rescan, enrich):
        assert (job["status"], job["error_code"]) == ("error", "login_required")
        assert job["error"].startswith(login.NO_SESSION)  # enrich adds what is missing
    assert status == 401
    assert test_send == {"detail": {"code": "login_required", "message": login.NO_SESSION}}
    with Session(fresh.engine) as s:
        row = s.get(models.Campaign, campaign["id"])
        assert row is not None
        assert (row.status, row.error) == ("paused", login.NO_SESSION)
        targets = s.exec(select(models.CampaignTarget)).all()
        assert [t.status for t in targets] == ["pending"]  # not burned
    assert sent == []
    _no_instagram(fresh)


def _status(f: Fresh, campaign_id: int) -> str:
    with Session(f.engine) as s:
        row = s.get(models.Campaign, campaign_id)
        return row.status if row is not None else "done"
