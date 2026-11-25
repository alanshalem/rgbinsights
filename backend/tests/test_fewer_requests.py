"""Fase 1: fewer Instagram requests (S0, S9-S12).

Every test counts the requests a flow makes. The adapter runs against a stub
instagrapi client that answers canned pages and records each request — including
the hidden media lookup instagrapi does when it only gets a bare media pk — so no
test ever reaches Instagram.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from app.application.use_cases import (
    RescanEventUseCase,
    ScanPostsUseCase,
    ScanPostUseCase,
    SyncDmsUseCase,
)
from app.application.use_cases._shared import KEY_DMS_SYNCED
from app.application.use_cases.sync import DmSyncResult
from app.domain.entities import Comment, DmInbox, FollowGraph, IgUser, Post
from app.domain.errors import InstagramError
from app.domain.result import Ok
from app.infrastructure.config.settings import Settings
from app.infrastructure.instagram.fake_source import FakeInstagramSource
from app.infrastructure.instagram.guard import IgGuard
from app.infrastructure.instagram.instagrapi_source import InstagrapiInstagramSource
from app.infrastructure.persistence import models
from app.infrastructure.persistence.repositories import AppStateRepository, EventRepository
from app.infrastructure.persistence.unit_of_work import SqlUnitOfWork
from instagrapi import Client
from sqlmodel import Session

T0 = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
MEDIA_LOOKUP = "media_info_v1"  # what instagrapi's media_id() costs for a bare pk


def _settings(tmp_path: Path, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "use_fake_instagram": False,
        "ig_source": "instagrapi",
        "ig_guard_file": str(tmp_path / "ig_guard.json"),
        "ig_session_file": str(tmp_path / "session.json"),
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


class StubClient:
    """The slice of instagrapi.Client the adapter's reads use; records every request."""

    def __init__(self) -> None:
        self.user_id = 1
        self.rank_token = "rank"
        self.requests: list[tuple[str, str, dict[str, Any]]] = []  # (endpoint, method, args)
        self.pages: dict[str, list[dict[str, Any]]] = {}
        self.inbox: list[tuple[list[Any], str | None]] = []

    def _record(
        self, endpoint: str, params: dict[str, Any] | None = None, method: str = "GET"
    ) -> None:
        self.requests.append((endpoint, method, dict(params or {})))

    def endpoints(self) -> list[str]:
        return [endpoint for endpoint, _, _ in self.requests]

    def private_request(
        self, endpoint: str, data: dict[str, Any] | None = None, params: Any = None, **kw: Any
    ) -> Any:
        # Like instagrapi: a data body makes it a signed POST, else a GET.
        self._record(endpoint, data or params, "POST" if data else "GET")
        pages = self.pages.get(endpoint, [])
        return pages.pop(0) if pages else {}

    def user_following(self, user_id: str, use_cache: bool = True, amount: int = 0) -> Any:
        # instagrapi's own paging, run over this stub's private_request.
        users, _ = Client.user_following_v1_chunk(self, str(user_id), amount)
        return {u.pk: u for u in users}

    def media_pk_from_url(self, url: str) -> str:
        return "5"  # decoded locally by instagrapi: no request

    def media_info(self, media_pk: str) -> Any:
        self._record("media_info")
        return _media("5", "5_77")

    def user_medias(self, user_id: int, amount: int = 0) -> list[Any]:
        self._record("user_medias")
        return [_media("5", "5_1"), _media("6", "6_1")]

    def media_id(self, media_pk: str) -> str:
        if "_" not in str(media_pk):
            self._record(MEDIA_LOOKUP)
            return f"{media_pk}_77"
        return str(media_pk)

    def media_likers(self, media_id: str) -> list[Any]:
        full = self.media_id(media_id)  # instagrapi resolves the full id first
        self._record(f"media/{full}/likers/")
        return [SimpleNamespace(pk=9, username="liker")]

    def user_followers_private_gql(self, user_id: str, amount: int = 0) -> list[Any]:
        self._record("followers_private_gql", {"amount": amount})
        return [SimpleNamespace(pk=pk) for pk in (1, 2, 3)]

    def direct_threads_chunk(
        self,
        selected_filter: str | None = None,
        box: str | None = None,
        thread_message_limit: int | None = None,
        cursor: str | None = None,
    ) -> tuple[list[Any], str | None]:
        self._record("direct_v2/inbox/", {"cursor": cursor, "message_limit": thread_message_limit})
        return self.inbox.pop(0) if self.inbox else ([], None)


def _media(pk: str, full_id: str) -> Any:
    return SimpleNamespace(
        pk=pk, id=full_id, code=f"C{pk}", caption_text="", taken_at=T0, user=SimpleNamespace(pk=77)
    )


def _source(tmp_path: Path, client: StubClient, **overrides: Any) -> InstagrapiInstagramSource:
    settings = _settings(tmp_path, **overrides)
    guard = IgGuard(settings, sleep=lambda _: None, rng=random.Random(1))
    source = InstagrapiInstagramSource(settings, guard=guard)
    source._client = client
    return source


# -- S11: DMs really incremental ------------------------------------------------


def _thread(n: int, activity: datetime, pinned: bool = False) -> Any:
    other = SimpleNamespace(pk=1000 + n, username=f"u{n}")
    return SimpleNamespace(
        id=f"t{n}",
        users=[SimpleNamespace(pk=1, username="us"), other],
        messages=[SimpleNamespace(user_id=1000 + n, timestamp=activity)],
        last_activity_at=activity,
        is_pin=pinned,
    )


def _inbox(start: int, count: int, newest: datetime) -> list[Any]:
    return [_thread(start + i, newest - timedelta(hours=start + i)) for i in range(count)]


def test_first_dm_sync_is_bounded_by_dm_threads_limit(tmp_path: Path) -> None:
    client = StubClient()
    client.inbox = [(_inbox(i * 20, 20, T0), f"c{i}") for i in range(5)]
    source = _source(tmp_path, client, dm_threads_limit=60, recent_posts_limit=5)

    inbox = source.get_dm_threads()

    assert client.endpoints() == ["direct_v2/inbox/"] * 3  # 60 threads = 3 pages, not 5
    assert len(inbox.threads) == 60
    assert [p["cursor"] for _, _, p in client.requests] == [None, "c0", "c1"]
    # instagrapi's own default (10 messages per thread), not an override.
    assert all(p["message_limit"] is None for _, _, p in client.requests)


def test_incremental_dm_sync_stops_paging_at_since(tmp_path: Path) -> None:
    client = StubClient()
    client.inbox = [(_inbox(i * 20, 20, T0), f"c{i}") for i in range(5)]
    source = _source(tmp_path, client)

    # Threads are 1 h apart, newest first: 5 changed after `since`.
    inbox = source.get_dm_threads(since=T0 - timedelta(hours=4, minutes=30))

    assert client.endpoints() == ["direct_v2/inbox/"]  # stopped on the first page
    assert [t.thread_id for t in inbox.threads] == ["t0", "t1", "t2", "t3", "t4"]
    assert inbox.complete


def test_incremental_dm_sync_pages_until_since_is_reached(tmp_path: Path) -> None:
    client = StubClient()
    client.inbox = [(_inbox(i * 20, 20, T0), f"c{i}") for i in range(5)]
    source = _source(tmp_path, client)

    inbox = source.get_dm_threads(since=T0 - timedelta(hours=25, minutes=30))

    assert len(client.requests) == 2
    assert len(inbox.threads) == 26
    assert inbox.complete


def test_incremental_dm_sync_with_an_old_since_stops_at_the_cap(tmp_path: Path) -> None:
    client = StubClient()
    client.inbox = [(_inbox(i * 20, 20, T0), f"c{i}") for i in range(30)]  # 600 threads
    source = _source(tmp_path, client, dm_threads_limit=60)

    inbox = source.get_dm_threads(since=T0 - timedelta(days=60))

    assert len(client.requests) == 3  # the same 3 pages as a first sync, not 30
    assert len(inbox.threads) == 60
    assert not inbox.complete  # older changed threads were left out


def test_incremental_dm_sync_compares_whole_seconds(tmp_path: Path) -> None:
    # instagrapi floors activity to whole seconds: a message at 12:00:00.7 reads
    # 12:00:00, so a sync that started at 12:00:00.5 must still pick it up.
    client = StubClient()
    client.inbox = [([_thread(1, T0), _thread(2, T0 - timedelta(seconds=1))], "c0")]
    source = _source(tmp_path, client)

    inbox = source.get_dm_threads(since=T0 + timedelta(milliseconds=500))

    assert [t.thread_id for t in inbox.threads] == ["t1"]
    assert len(client.requests) == 1


def test_pinned_old_thread_does_not_stop_incremental_dm_sync(tmp_path: Path) -> None:
    client = StubClient()
    old = T0 - timedelta(days=30)
    client.inbox = [
        ([_thread(1, old, pinned=True), _thread(2, T0), _thread(3, T0)], "c0"),
        ([_thread(4, T0 - timedelta(hours=1)), _thread(5, old)], "c1"),
        (_inbox(10, 3, old), None),
    ]
    source = _source(tmp_path, client)

    inbox = source.get_dm_threads(since=T0 - timedelta(hours=2))

    assert len(client.requests) == 2
    assert [t.thread_id for t in inbox.threads] == ["t2", "t3", "t4"]


def test_dm_sync_with_naive_local_activity_compares_in_utc(tmp_path: Path) -> None:
    # instagrapi builds last_activity_at with datetime.fromtimestamp: naive local time.
    client = StubClient()
    newer = (T0 + timedelta(minutes=5)).astimezone().replace(tzinfo=None)
    older = (T0 - timedelta(minutes=5)).astimezone().replace(tzinfo=None)
    client.inbox = [([_thread(1, newer), _thread(2, older)], "c0")]
    source = _source(tmp_path, client)

    inbox = source.get_dm_threads(since=T0)

    assert [t.thread_id for t in inbox.threads] == ["t1"]
    assert len(client.requests) == 1


# -- S12: comments incremental --------------------------------------------------


def _comment(pk: int, at: datetime) -> dict[str, Any]:
    return {
        "pk": str(pk),
        "text": f"c{pk}",
        "user": {"pk": str(500 + pk), "username": f"fan{pk}"},
        "created_at_utc": int(at.timestamp()),
        "content_type": "comment",
        "status": "Active",
    }


def _comment_pages(endpoint: str, pages: int, per_page: int) -> dict[str, list[dict[str, Any]]]:
    out = []
    for p in range(pages):
        # Each page holds older comments than the previous one (newest page first).
        items = [
            _comment(p * per_page + i, T0 - timedelta(minutes=p * per_page + i))
            for i in range(per_page)
        ]
        last = p == pages - 1
        out.append(
            {
                "comments": list(reversed(items)),  # oldest first inside a page
                "has_more_comments": not last,
                "next_max_id": "" if last else f"m{p}",
            }
        )
    return {endpoint: out}


def test_incremental_comments_stop_at_the_known_one(tmp_path: Path) -> None:
    client = StubClient()
    client.pages = _comment_pages("media/5_77/comments/", pages=4, per_page=5)
    source = _source(tmp_path, client)
    source.get_post("https://instagram.com/p/C5/")
    client.requests.clear()

    comments = source.get_comments("5", since=T0 - timedelta(minutes=7))

    # Page 2 still holds newer comments; page 3 is the first one all known.
    assert client.endpoints() == ["media/5_77/comments/"] * 3  # not all 4 pages
    assert sorted(c.text for c in comments) == [f"c{i}" for i in range(8)]  # >= since


def test_an_old_pinned_comment_does_not_stop_paging_early(tmp_path: Path) -> None:
    client = StubClient()
    client.pages = {
        "media/5_77/comments/": [
            {  # a pinned comment from long ago ranked on top of a new one
                "comments": [_comment(1, T0 - timedelta(days=9)), _comment(2, T0)],
                "has_more_comments": True,
                "next_max_id": "m1",
            },
            {
                "comments": [_comment(3, T0 - timedelta(minutes=30))],
                "has_more_comments": True,
                "next_max_id": "m2",
            },
            {
                "comments": [_comment(4, T0 - timedelta(hours=2))],
                "has_more_comments": True,
                "next_max_id": "m3",
            },
        ]
    }
    source = _source(tmp_path, client)

    comments = source.get_comments("5_77", since=T0 - timedelta(hours=1))

    assert sorted(c.text for c in comments) == ["c2", "c3"]
    assert len(client.requests) == 3  # stopped after the first page that is all known


def test_full_comment_read_is_capped_like_before(tmp_path: Path) -> None:
    client = StubClient()
    client.pages = _comment_pages("media/5_77/comments/", pages=4, per_page=5)
    source = _source(tmp_path, client, scan_comments_limit=8)
    source.get_post("https://instagram.com/p/C5/")
    client.requests.clear()

    comments = source.get_comments("5")

    # Same requests as instagrapi's media_comments: the cursor goes as a POST body.
    assert client.requests == [
        ("media/5_77/comments/", "GET", {}),
        ("media/5_77/comments/", "POST", {"max_id": "m0"}),
    ]
    assert len(comments) == 8


# -- S10: no media lookup for a post we already know ----------------------------


def test_scan_of_a_fetched_post_makes_no_extra_media_lookups(tmp_path: Path) -> None:
    client = StubClient()
    source = _source(tmp_path, client)

    post = source.get_post("https://instagram.com/p/C5/")
    source.get_comments(post.media_pk)
    source.get_likers(post.media_pk)

    # Before: media_info + one hidden media lookup for comments + one for likers.
    assert client.endpoints() == ["media_info", "media/5_77/comments/", "media/5_77/likers/"]


def test_posts_listed_by_user_medias_need_no_media_lookup(tmp_path: Path) -> None:
    client = StubClient()
    source = _source(tmp_path, client)

    posts = source.get_recent_posts(5)
    for post in posts:
        source.get_comments(post.media_pk)
        source.get_likers(post.media_pk)

    assert MEDIA_LOOKUP not in client.endpoints()
    assert "media_info" not in client.endpoints()


def test_unknown_media_pk_is_resolved_once_for_comments_and_likers(tmp_path: Path) -> None:
    client = StubClient()
    source = _source(tmp_path, client)

    source.get_comments("5")
    source.get_likers("5")

    assert client.endpoints().count(MEDIA_LOOKUP) == 1  # before: one per call


# -- S9: followers/following incremental ----------------------------------------


def _users(*pks: int) -> list[dict[str, Any]]:
    return [{"pk": pk, "username": f"u{pk}"} for pk in pks]


FOLLOWERS = "friendships/1/followers/"
FOLLOWING = "friendships/1/following/"


def test_full_graph_read_pages_everything_newest_first(tmp_path: Path) -> None:
    client = StubClient()
    client.pages = {
        FOLLOWERS: [
            {"users": _users(1, 2), "next_max_id": "f1"},
            {"users": _users(3), "next_max_id": None},
        ],
        FOLLOWING: [{"users": _users(2, 4), "next_max_id": None}],
    }
    source = _source(tmp_path, client)

    graph = source.get_follow_graph()

    assert graph == FollowGraph(followers={"1", "2", "3"}, following={"2", "4"})
    assert client.endpoints() == [FOLLOWERS, FOLLOWERS, FOLLOWING]
    followers, following = client.requests[:2], client.requests[2:]
    assert all(p["order"] == "date_followed_latest" for _, _, p in followers)
    assert all("order" not in p for _, _, p in following)  # instagrapi sends none there
    assert client.requests[1][2]["max_id"] == "f1"


def test_incremental_graph_read_stops_at_a_page_of_known_people(tmp_path: Path) -> None:
    client = StubClient()
    client.pages = {
        FOLLOWERS: [
            {"users": _users(10, 1), "next_max_id": "f1"},
            {"users": _users(2, 3), "next_max_id": "f2"},
            {"users": _users(4, 5), "next_max_id": None},
        ],
        FOLLOWING: [
            {"users": _users(2), "next_max_id": "g1"},
            {"users": _users(4), "next_max_id": None},
        ],
    }
    source = _source(tmp_path, client)
    known = FollowGraph(followers={"1", "2", "3", "4", "5"}, following={"2", "4"})

    graph = source.get_follow_graph(known)

    # New followers only; following has no guaranteed order, so it is read whole.
    assert graph == FollowGraph(followers={"10"}, following={"2", "4"})
    assert client.endpoints() == [FOLLOWERS, FOLLOWERS, FOLLOWING, FOLLOWING]  # before: 5


def test_truncated_followers_list_falls_back_to_the_full_read(tmp_path: Path) -> None:
    client = StubClient()
    client.pages = {
        FOLLOWERS: [
            {"users": _users(1), "next_max_id": "f1", "should_limit_list_of_followers": True}
        ],
        FOLLOWING: [{"users": _users(2), "next_max_id": None}],
    }
    source = _source(tmp_path, client)

    graph = source.get_follow_graph(FollowGraph(followers={"1"}, following={"2"}))

    assert graph == FollowGraph(followers={"2", "3"}, following={"2"})
    assert client.endpoints() == [FOLLOWERS, "followers_private_gql", FOLLOWING]


def test_graph_read_that_returns_nobody_is_refused(tmp_path: Path) -> None:
    client = StubClient()
    client.pages = {FOLLOWERS: [{"users": []}], FOLLOWING: [{"users": []}]}
    source = _source(tmp_path, client)

    with pytest.raises(InstagramError) as info:
        source.get_follow_graph()
    assert "bloqueado" in str(info.value)


# -- use cases: request counts ----------------------------------------------------


class CountingSource(FakeInstagramSource):
    """The fake source, recording each port call and its arguments."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple[str, Any]] = []

    def get_post(self, url: str) -> Post:
        self.calls.append(("get_post", url))
        return super().get_post(url)

    def get_recent_posts(self, limit: int) -> list[Post]:
        self.calls.append(("get_recent_posts", limit))
        return super().get_recent_posts(limit)

    def get_comments(self, media_pk: str, since: datetime | None = None) -> list[Comment]:
        self.calls.append(("get_comments", since))
        return super().get_comments(media_pk, since)

    def get_likers(self, media_pk: str) -> list[IgUser]:
        self.calls.append(("get_likers", media_pk))
        return super().get_likers(media_pk)

    def get_dm_threads(self, since: datetime | None = None) -> DmInbox:
        self.calls.append(("get_dm_threads", since))
        return super().get_dm_threads(since)

    def names(self) -> list[str]:
        return [name for name, _ in self.calls]


POST_A = "https://instagram.com/p/Cabc123/"


def _event(session: Session) -> int:
    event = EventRepository(session).create(
        models.Event(
            name="Fiesta",
            promo_start=datetime(2026, 6, 1, tzinfo=UTC),
            event_date=datetime(2026, 6, 30, tzinfo=UTC),
            created_at=datetime(2026, 6, 1, tzinfo=UTC),
        )
    )
    assert event.id is not None
    return event.id


def test_scan_of_a_new_post_fetches_it_once(session: Session) -> None:
    source = CountingSource()

    result = ScanPostUseCase(source, SqlUnitOfWork(session)).execute(POST_A)

    assert isinstance(result, Ok)
    assert source.names() == ["get_post", "get_comments", "get_likers"]
    assert source.calls[1] == ("get_comments", None)  # nothing stored yet: full read


def test_rescan_of_a_known_post_never_refetches_it(session: Session) -> None:
    source = CountingSource()
    event_id = _event(session)
    ScanPostUseCase(source, SqlUnitOfWork(session)).execute(POST_A, event_id=event_id)
    source.calls.clear()

    result = RescanEventUseCase(source, SqlUnitOfWork(session)).execute(event_id, force=True)

    assert isinstance(result, Ok)
    assert len(result.value.results) == 1
    assert source.names() == ["get_comments", "get_likers"]  # 0 get_post (media_info)


def test_pasting_a_known_post_url_again_skips_get_post(session: Session) -> None:
    source = CountingSource()
    ScanPostUseCase(source, SqlUnitOfWork(session)).execute(POST_A)
    source.calls.clear()

    ScanPostUseCase(source, SqlUnitOfWork(session)).execute(
        "https://www.instagram.com/p/Cabc123/?igsh=x"
    )

    assert "get_post" not in source.names()


def test_rescan_asks_only_for_comments_newer_than_the_stored_ones(session: Session) -> None:
    source = CountingSource()
    ScanPostUseCase(source, SqlUnitOfWork(session)).execute(POST_A)
    source.calls.clear()

    ScanPostUseCase(source, SqlUnitOfWork(session)).execute(POST_A)

    # Fake post A's newest comment is Jun 11 12:00 UTC.
    assert source.calls[0] == ("get_comments", datetime(2026, 6, 11, 12, 0, tzinfo=UTC))


def test_scan_by_date_range_does_not_refetch_listed_posts(session: Session) -> None:
    source = CountingSource()

    result = ScanPostsUseCase(source, SqlUnitOfWork(session)).by_date_range(
        datetime(2026, 6, 1, tzinfo=UTC), datetime(2026, 6, 30, tzinfo=UTC), recent_limit=50
    )

    assert isinstance(result, Ok)
    assert len(result.value.results) == 2
    assert source.names().count("get_recent_posts") == 1
    assert "get_post" not in source.names()


def test_dm_sync_since_is_the_previous_sync_start(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = CountingSource()
    starts = iter([T0, T0 + timedelta(hours=1), T0 + timedelta(hours=2)])
    monkeypatch.setattr("app.application.use_cases.sync._now", lambda: next(starts))

    first = SyncDmsUseCase(source, SqlUnitOfWork(session)).execute()
    second = SyncDmsUseCase(source, SqlUnitOfWork(session)).execute()

    assert isinstance(first, Ok) and isinstance(second, Ok)
    assert source.calls == [("get_dm_threads", None), ("get_dm_threads", T0)]
    assert (first.value.incremental, second.value.incremental) == (False, True)
    assert first.value.threads_synced == 2
    assert second.value.threads_synced == 0  # nothing changed since T0 (fake data is June)


class CappedSource(CountingSource):
    """An inbox whose incremental reads always hit the thread cap."""

    def get_dm_threads(self, since: datetime | None = None) -> DmInbox:
        inbox = super().get_dm_threads(since)
        return DmInbox(threads=inbox.threads, complete=since is None)


def test_dm_sync_cut_short_by_the_cap_says_so(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    starts = iter([T0, T0 + timedelta(hours=1)])
    monkeypatch.setattr("app.application.use_cases.sync._now", lambda: next(starts))
    source = CappedSource()

    first = SyncDmsUseCase(source, SqlUnitOfWork(session)).execute()
    second = SyncDmsUseCase(source, SqlUnitOfWork(session)).execute()

    assert isinstance(first, Ok) and isinstance(second, Ok)
    assert isinstance(first.value, DmSyncResult) and isinstance(second.value, DmSyncResult)
    assert (first.value.capped, second.value.capped) == (False, True)
    assert second.value.incremental is True
    # The watermark still moves to this sync's start (kept simple, documented).
    assert AppStateRepository(session).get_dt(KEY_DMS_SYNCED) == T0 + timedelta(hours=1)
