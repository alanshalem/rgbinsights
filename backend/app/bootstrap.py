"""Composition root (S18): the one place that builds the concrete parts and
wires them together — settings, the DB engine and units of work, the in-app
configuration, the Instagram source and its guard, the job registry and the
campaign sender.

Use cases, jobs and the sender only see the ports (app.application.ports);
the API reaches these objects through app.api.deps.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from sqlmodel import Session

from app.application.campaign_sender import CampaignSender
from app.application.ports import InstagramSource
from app.application.runtime_config import RuntimeConfigService
from app.application.tasks import TaskRegistry, log_activity
from app.infrastructure.config.settings import Settings, get_settings
from app.infrastructure.instagram.guard import IgGuard, get_guard
from app.infrastructure.persistence.campaigns import SqlCampaignStore
from app.infrastructure.persistence.config_store import SqlConfigStore
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


# The in-app configuration (S25): stored overrides over the .env/factory defaults.
runtime_config = RuntimeConfigService(
    SqlConfigStore(new_session),
    lambda: get_settings().runtime_defaults(),
)


def effective_settings() -> Settings:
    """The settings with the effective in-app configuration."""
    return get_settings().with_runtime(runtime_config.current())


def build_source(settings: Settings) -> InstagramSource:
    """The real Instagram adapter (it reads the in-app configuration at every
    request), or the fake one for development/tests (RGB_DEV_FAKE_INSTAGRAM=1)."""
    if settings.is_fake:
        from app.infrastructure.instagram.fake_source import FakeInstagramSource

        return FakeInstagramSource()
    from app.infrastructure.instagram.instagrapi_source import InstagrapiInstagramSource

    config = runtime_config.current
    return InstagrapiInstagramSource(settings, get_guard(settings, config), config)


def build_guard(settings: Settings) -> IgGuard:
    """The process-wide guard, reading the in-app configuration."""
    return get_guard(settings, runtime_config.current)


class InstagramAccess:
    """The process-wide Instagram source, shared by the API, the jobs and the
    campaign sender so they reuse the SAME session (one login, one device)
    instead of each building its own; plus its guard, for status reads."""

    def __init__(
        self,
        build: Callable[[Settings], InstagramSource] = build_source,
        guard: Callable[[Settings], IgGuard] = build_guard,
        settings: Callable[[], Settings] = effective_settings,
    ) -> None:
        self._build = build
        self._guard = guard
        self._settings = settings
        self._sources: dict[str, InstagramSource] = {}
        self._lock = threading.Lock()

    def source(self, settings: Settings | None = None) -> InstagramSource:
        """The shared source for `settings` (by default the effective ones)."""
        settings = settings or self._settings()
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
