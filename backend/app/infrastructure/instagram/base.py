"""InstagramSource port (Strategy).

Isolates the fragile IG/ToS-bound access behind a stable interface so the
use cases depend only on this, and tests can swap in a Fake. The real
implementation is InstagrapiInstagramSource; tests use FakeInstagramSource.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable

from app.domain.entities import (
    Comment,
    DmThread,
    IgUser,
    Post,
    ProfileInfo,
)

ProgressFn = Callable[..., None]


@dataclass(frozen=True, slots=True)
class FollowGraph:
    """Our account's follow lists, as user pks."""

    followers: set[str] = field(default_factory=set)  # they follow us
    following: set[str] = field(default_factory=set)  # we follow them


@dataclass(frozen=True, slots=True)
class DmInbox:
    """DM threads from one inbox read."""

    threads: list[DmThread] = field(default_factory=list)
    # False when the thread cap stopped an incremental read before it got back
    # to the previous sync: older threads with new messages were left out.
    complete: bool = True


@runtime_checkable
class InstagramSource(Protocol):
    def current_user_pk(self) -> str:
        """Our own account pk. Used to classify DM message direction. Logs in if
        needed, so only call it from a user-initiated operation."""
        ...

    def cached_user_pk(self) -> str | None:
        """Our pk if a session is already live in memory, else None. Never
        touches the network (safe for status polling)."""
        ...

    def connect_sessionid(self, sessionid: str) -> str:
        """Explicit user action: adopt a browser sessionid, validate it once,
        persist it, and return our pk."""
        ...

    def get_post(self, url: str) -> Post:
        """Raise PostNotFoundError if the url resolves to nothing."""
        ...

    def get_recent_posts(self, limit: int) -> list[Post]: ...

    def get_likers(self, media_pk: str) -> list[IgUser]: ...

    def get_comments(self, media_pk: str, since: datetime | None = None) -> list[Comment]:
        """Newest comments first, capped. With `since` (the newest comment
        already stored) stop paging once reached; returns comments at/after it."""
        ...

    def get_dm_threads(
        self, progress: ProgressFn | None = None, since: datetime | None = None
    ) -> DmInbox:
        """DM threads, newest activity first, at most dm_threads_limit per read.
        With `since`, stop paging at the first thread not active since then and
        return only the threads that changed (incremental sync); `complete` is
        False if the cap stopped it first."""
        ...

    def send_dm(self, user_pk: str, text: str) -> None:
        """Send a DM. Raises SendBlockedError if Instagram refuses (spam /
        feedback_required), SendNotSupportedError if the source can't send."""
        ...

    def get_follow_graph(self, known: FollowGraph | None = None) -> FollowGraph:
        """Our followers/following. Without `known`, both full lists. With the
        lists from earlier reads, followers are paged newest-first only until a
        page of known people and just the NEW followers are returned (unfollows
        need a full read); `following` is always the full list."""
        ...

    def get_profile(self, username: str) -> ProfileInfo:
        """Richer profile fields (follower count, verified, bio)."""
        ...

    def reset_budget(self) -> None:
        """Kept for callers; a no-op now. The request budget is real and
        process-wide (per hour/day, every HTTP request), enforced by IgGuard."""
        ...
