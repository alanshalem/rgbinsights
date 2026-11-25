"""InstagrapiInstagramSource — the real adapter, a thin facade over its parts.

- login.py          the session (pasted sessionid -> session.json, reused)
- reads.py          posts, comments, likers, profiles, follow graph
- direct.py         DM inbox and sending
- error_mapping.py  instagrapi/network exceptions -> domain errors

Every port method runs as one IgGuard operation (guard.py), which serializes
Instagram access and enforces the login breaker, cooldown, request budget and
human pacing. instagrapi is imported lazily so the app (and the fake source)
boots even when the package isn't installed; only these modules know about
instagrapi's models and exceptions, everything else sees domain entities.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING, Any

from app.domain.config import RuntimeConfig
from app.domain.entities import Comment, DmInbox, FollowGraph, IgUser, Post, ProfileInfo
from app.infrastructure.config.settings import Settings
from app.infrastructure.instagram import direct
from app.infrastructure.instagram.error_mapping import to_instagram_error
from app.infrastructure.instagram.guard import IgGuard, get_guard
from app.infrastructure.instagram.login import IgLogin
from app.infrastructure.instagram.reads import IgReader
from app.infrastructure.instagram.session import take_session_failure

if TYPE_CHECKING:
    from instagrapi import Client


def _adapts[F: Callable[..., Any]](fn: F) -> F:
    """Run a port method as one guarded Instagram operation, turning any raw
    instagrapi/network exception into an InstagramError (our own errors already
    pass through). Defined before the class because decorators are evaluated
    when the class body runs.
    """

    @functools.wraps(fn)
    def wrapper(source: InstagrapiInstagramSource, *args: Any, **kwargs: Any) -> Any:
        with source._guard.operation():
            return _call_adapted(fn, source, *args, **kwargs)

    return wrapper  # type: ignore[return-value]


def _call_adapted(
    fn: Callable[..., Any], source: InstagrapiInstagramSource, *args: Any, **kwargs: Any
) -> Any:
    if (client := source._client) is not None:
        take_session_failure(client)  # discard a stale record from an earlier call
    try:
        return fn(source, *args, **kwargs)
    except Exception as exc:  # noqa: BLE001 — normalised at the adapter boundary
        err = to_instagram_error(exc)
        # instagrapi may swallow a session failure and report a misleading
        # fallback error (e.g. "not found"); the real cause wins.
        client = source._client
        if client is not None and (failure := take_session_failure(client)) is not None:
            err = to_instagram_error(failure)
        # A dead session's cookies are gone: drop the client (a new paste is needed).
        source._login.forget_if_dead(err)
        if err is exc:
            raise
        raise err from exc


class InstagrapiInstagramSource:
    """Adapter over instagrapi.Client implementing the InstagramSource port."""

    def __init__(
        self,
        settings: Settings,
        guard: IgGuard | None = None,
        config: Callable[[], RuntimeConfig] | None = None,
    ) -> None:
        """`config`: the effective in-app configuration (S25), read at every
        request/read; without it `settings`' own values are used."""
        self._config = config or settings.runtime_defaults
        self._guard = guard or get_guard(settings, config)
        self._login = IgLogin(settings, self._guard)
        self._reads = IgReader(settings, self._config)

    @property
    def _client(self) -> Client | None:
        """The logged-in client in memory (None until a login)."""
        return self._login.client

    @_client.setter
    def _client(self, client: Client | None) -> None:
        self._login.client = client

    # -- session -----------------------------------------------------------

    def cached_user_pk(self) -> str | None:
        return self._login.cached_user_pk()

    def connect_sessionid(self, sessionid: str) -> str:
        return self._login.connect_sessionid(sessionid)

    @_adapts
    def current_user_pk(self) -> str:
        return str(self._login.client_or_login().user_id)

    # -- reads -------------------------------------------------------------

    @_adapts
    def get_follow_graph(self, known: FollowGraph | None = None) -> FollowGraph:
        return self._reads.follow_graph(self._login.client_or_login(), known)

    @_adapts
    def get_profile(self, username: str) -> ProfileInfo:
        return self._reads.profile(self._login.client_or_login(), username)

    @_adapts
    def get_post(self, url: str) -> Post:
        return self._reads.post(self._login.client_or_login(), url)

    @_adapts
    def get_recent_posts(self, limit: int) -> list[Post]:
        return self._reads.recent_posts(self._login.client_or_login(), limit)

    @_adapts
    def get_likers(self, media_pk: str) -> list[IgUser]:
        return self._reads.likers(self._login.client_or_login(), media_pk)

    @_adapts
    def get_comments(self, media_pk: str, since: datetime | None = None) -> list[Comment]:
        return self._reads.comments(self._login.client_or_login(), media_pk, since)

    # -- direct messages -----------------------------------------------------

    @_adapts
    def get_dm_threads(self, since: datetime | None = None) -> DmInbox:
        client = self._login.client_or_login()
        return direct.read_inbox(client, self._config().dm_threads_limit, since)

    def send_dm(self, user_pk: str, text: str) -> None:
        # Besides the campaign's own rails (per-send delay + daily cap), the send's
        # HTTP requests count in the guard's hourly/daily budget like any other.
        # Hitting it raises RateLimitedError (a pause), never a fake action-block.
        with self._guard.operation():
            recipient = direct.parse_recipient(user_pk)
            client = self._login.client_or_login()
            direct.send_text(client, user_pk, recipient, text, self._login.forget_if_dead)
