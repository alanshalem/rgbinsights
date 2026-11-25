"""Composition root (S18): the one place that builds the concrete parts and
wires them together — settings, the DB engine and units of work, the Instagram
source and its guard, the job registry and the campaign sender.

Use cases, jobs and the sender only see the ports (app.application.ports);
the API reaches these objects through app.api.deps.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from sqlmodel import Session

from app.application.campaign_sender import CampaignSender
from app.application.ports import InstagramSource
from app.application.tasks import TaskRegistry, log_activity
from app.infrastructure.config.settings import Settings, get_settings
from app.infrastructure.instagram.guard import IgGuard, get_guard
from app.infrastructure.persistence.campaigns import SqlCampaignStore
from app.infrastructure.persistence.db import build_engine
from app.infrastructure.persistence.unit_of_work import SqlUnitOfWork

engine = build_engine(get_settings().database_url)


def new_session() -> Session:
    return Session(engine)


def unit_of_work(session: Session) -> SqlUnitOfWork:
    return SqlUnitOfWork(session)


def new_unit_of_work() -> SqlUnitOfWork:
    """A unit of work with its own session (closed when the `with` ends)."""
    return SqlUnitOfWork(new_session())


def build_source(settings: Settings) -> InstagramSource:
    """The InstagramSource for IG_SOURCE: the fake (demo) or the real adapter."""
    if settings.is_fake:
        from app.infrastructure.instagram.fake_source import FakeInstagramSource

        return FakeInstagramSource()
    from app.infrastructure.instagram.instagrapi_source import InstagrapiInstagramSource

    return InstagrapiInstagramSource(settings)


class InstagramAccess:
    """The process-wide Instagram source, shared by the API, the jobs and the
    campaign sender so they reuse the SAME session (one login, one device)
    instead of each building its own; plus its guard, for status reads."""

    def __init__(
        self,
        build: Callable[[Settings], InstagramSource] = build_source,
        guard: Callable[[Settings], IgGuard] = get_guard,
    ) -> None:
        self._build = build
        self._guard = guard
        self._sources: dict[str, InstagramSource] = {}
        self._lock = threading.Lock()

    def source(self, settings: Settings | None = None) -> InstagramSource:
        settings = settings or get_settings()
        with self._lock:
            found = self._sources.get(settings.ig_source)
            if found is None:
                found = self._sources[settings.ig_source] = self._build(settings)
            return found

    def guard(self, settings: Settings) -> IgGuard:
        return self._guard(settings)

    def reset(self) -> None:
        """Forget the shared source so the next call builds a fresh one. Used
        after an in-app reconnect/disconnect: the cached session goes and the
        next Instagram operation picks up the new (or absent) session.json."""
        with self._lock:
            self._sources.clear()


instagram = InstagramAccess()
registry = TaskRegistry()


def record_activity(kind: str, status: str, message: str) -> None:
    log_activity(new_unit_of_work, kind, status, message)


campaign_sender = CampaignSender(
    SqlCampaignStore(new_session),
    instagram.source,
    get_settings().local_tz(),
    record_activity,
)
