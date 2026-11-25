"""Ports: the interfaces the application layer talks to (S18).

Use cases, jobs and the campaign sender depend only on these Protocols; the
infrastructure implements them (instagrapi/fake Instagram sources, SQLite
repositories) and the composition root (`app.bootstrap`) wires one to the
other. Only what a caller actually uses is declared here.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol, runtime_checkable

from app.domain.entities import (
    Comment,
    DmInbox,
    EngagementType,
    FollowGraph,
    Friendship,
    IgUser,
    Post,
    ProfileInfo,
)
from app.domain.traffic_light import TrafficLight

# progress(current, total, message): how a long operation reports where it is.
ProgressFn = Callable[[int, int, str], None]

# -- Instagram -------------------------------------------------------------------


@runtime_checkable
class InstagramSource(Protocol):
    """Instagram access (Strategy): the real instagrapi adapter or the fake.

    Every method raises only the domain InstagramError family.
    """

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

    def get_dm_threads(self, since: datetime | None = None) -> DmInbox:
        """DM threads, newest activity first, at most dm_threads_limit per read.
        With `since`, stop paging at the first thread not active since then and
        return only the threads that changed (incremental sync); `complete` is
        False if the cap stopped it first."""
        ...

    def send_dm(self, user_pk: str, text: str) -> None:
        """Send a DM. Raises SendBlockedError if Instagram refuses (spam /
        feedback_required)."""
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


# -- stored data (what the repositories hand back) --------------------------------


class StoredUser(Protocol):
    @property
    def pk(self) -> str: ...
    @property
    def username(self) -> str: ...


class StoredPost(Protocol):
    @property
    def url(self) -> str: ...
    @property
    def shortcode(self) -> str: ...
    @property
    def last_scanned_at(self) -> datetime | None: ...


class StoredEvent(Protocol):
    @property
    def name(self) -> str: ...


@dataclass(frozen=True, slots=True)
class EngagementIn:
    user_pk: str
    type: EngagementType
    comment_text: str | None = None
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ThreadIn:
    thread_id: str
    user_pk: str
    has_outgoing: bool
    has_incoming: bool
    last_outgoing_at: datetime | None
    last_incoming_at: datetime | None
    last_message_at: datetime | None


@dataclass(frozen=True, slots=True)
class UserFilter:
    event: int | None = None
    post: str | None = None
    search: str | None = None
    follows: bool | None = None


@dataclass(frozen=True, slots=True)
class UserRow:
    pk: str
    username: str
    full_name: str
    profile_pic_url: str | None
    is_private: bool
    follows_us: bool | None
    we_follow: bool | None
    follower_count: int | None
    is_verified: bool
    is_business: bool
    biography: str | None
    thread_id: str | None
    last_message_at: datetime | None
    traffic_light: TrafficLight
    fans: int  # distinct posts engaged, global
    event_engaged: int  # distinct posts engaged within the filter
    last_engaged_at: datetime | None


@dataclass(frozen=True, slots=True)
class EngagementRow:
    post_media_pk: str
    type: EngagementType
    comment_text: str | None
    post_url: str | None


# -- repositories -------------------------------------------------------------------


class UserRepo(Protocol):
    def upsert_many(self, users: Iterable[IgUser], now: datetime) -> set[str]:
        """Upsert by pk; returns the pks that were newly inserted."""
        ...

    def set_friendships(self, rels: dict[str, Friendship]) -> None: ...

    def set_profile(self, pk: str, profile: ProfileInfo, now: datetime) -> None: ...

    def profiles_synced_since(self, since: datetime) -> int: ...

    def unenriched(self, pks: list[str]) -> Sequence[StoredUser]:
        """Users among `pks` whose profile was never fetched, in input order."""
        ...


class PostRepo(Protocol):
    def upsert(
        self,
        post: Post,
        scanned_at: datetime,
        event_id: int | None = None,
        last_comment_at: datetime | None = None,
    ) -> None: ...

    def find_by_shortcode(self, shortcode: str) -> Post | None: ...

    def last_comment_at(self, media_pk: str) -> datetime | None: ...

    def list_all(self, event_id: int | None = None) -> Sequence[StoredPost]: ...

    def get(self, media_pk: str) -> StoredPost | None: ...


class EngagementRepo(Protocol):
    def upsert_many(self, post_media_pk: str, items: Iterable[EngagementIn]) -> None: ...


class DmThreadRepo(Protocol):
    def upsert_many(self, threads: Iterable[ThreadIn], synced_at: datetime) -> None: ...


class FollowGraphRepo(Protocol):
    def load(self) -> tuple[set[str], set[str]]:
        """(followers, following)."""
        ...

    def replace(self, followers: set[str], following: set[str]) -> None: ...

    def replace_following(self, following: set[str]) -> None: ...

    def add_followers(self, followers: set[str]) -> None: ...


class EventRepo(Protocol):
    def get(self, event_id: int) -> StoredEvent | None: ...


class AppStateRepo(Protocol):
    def get_dt(self, key: str) -> datetime | None: ...

    def set_dt(self, key: str, when: datetime) -> None: ...


class ActivityRepo(Protocol):
    def add(self, kind: str, status: str, message: str) -> None: ...


class ConfigStore(Protocol):
    """The in-app configuration overrides (S25): key -> value, only for the
    settings the user changed. Each call is its own transaction."""

    def load(self) -> dict[str, object]: ...

    def save(self, values: Mapping[str, object]) -> None:
        """Insert or replace these overrides."""
        ...

    def delete(self, keys: Iterable[str] | None = None) -> None:
        """Drop these overrides (all of them with None): back to the defaults."""
        ...


class UserListReader(Protocol):
    """The board's read model: filter, order, count and page users."""

    def page(
        self,
        f: UserFilter,
        status: TrafficLight | None,
        order: str,
        limit: int | None,
        offset: int,
    ) -> list[UserRow]: ...

    def counts(self, f: UserFilter) -> dict[TrafficLight, int]: ...

    def engagements(
        self, f: UserFilter, user_pks: Sequence[str]
    ) -> dict[str, list[EngagementRow]]: ...

    def event_posts_total(self, f: UserFilter) -> int: ...


class UnitOfWork(Protocol):
    """Every repository over ONE database transaction; `commit()` ends it."""

    @property
    def users(self) -> UserRepo: ...
    @property
    def posts(self) -> PostRepo: ...
    @property
    def engagements(self) -> EngagementRepo: ...
    @property
    def dm_threads(self) -> DmThreadRepo: ...
    @property
    def follow_graph(self) -> FollowGraphRepo: ...
    @property
    def events(self) -> EventRepo: ...
    @property
    def app_state(self) -> AppStateRepo: ...
    @property
    def activity(self) -> ActivityRepo: ...
    @property
    def user_list(self) -> UserListReader: ...

    def commit(self) -> None: ...


# A new unit of work for work that outlives the request (a job's worker thread).
UnitOfWorkFactory = Callable[[], AbstractContextManager[UnitOfWork]]

# -- campaigns ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CampaignDay:
    """A campaign as the sender needs it for one loop turn."""

    status: str
    created_at: datetime
    daily_cap: int
    sent_today: int  # within the current local day
    hour_start: int
    hour_end: int
    delay_min: int
    delay_max: int


@dataclass(frozen=True, slots=True)
class PendingSend:
    target_id: int | None
    user_pk: str
    message: str


class CampaignStore(Protocol):
    """Campaign state for the background sender; each call is its own transaction."""

    def running_ids(self) -> list[int]: ...

    def status(self, campaign_id: int) -> str:
        """The campaign's status ("done" if it no longer exists)."""
        ...

    def open_day(self, campaign_id: int, today: date) -> CampaignDay | None:
        """The campaign, a running one's daily counter reset (and saved) when
        `today` (local date) is a new day; None if it no longer exists."""
        ...

    def next_pending(self, campaign_id: int) -> PendingSend | None: ...

    def finish(self, campaign_id: int) -> None: ...

    def halt(self, campaign_id: int, status: str, error: str) -> None: ...

    def record_send(
        self,
        campaign_id: int,
        target_id: int | None,
        outcome: str,
        error: str | None,
        at: datetime,
    ) -> None: ...
