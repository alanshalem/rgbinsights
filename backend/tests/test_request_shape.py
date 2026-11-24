"""S0: every request our adapter sends has exactly the shape instagrapi itself sends.

instagrapi mirrors the official Android app, so any deviation (endpoint, HTTP
method, query params vs signed POST body, param keys/order/values, page size) is
a fingerprint. Each test runs a REAL instagrapi Client twice over the same canned
pages — once through instagrapi's own public method, once through our adapter —
with only `private_request` replaced by a recorder, and compares the sequences.
"""

from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.infrastructure.instagram.base import FollowGraph
from instagrapi import Client

from tests.test_fewer_requests import _source

# Values instagrapi randomizes per client/request: not part of the shape.
_VOLATILE = {"rank_token", "igd_request_log_tracking_id"}
T0 = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)

Request = tuple[str, str, list[tuple[str, Any]] | None, list[tuple[str, Any]]]


def _rec(pages: list[dict[str, Any]]) -> tuple[Client, list[Request]]:
    client = Client()
    client.authorization_data = {"ds_user_id": "999", "sessionid": "x"}
    pages = copy.deepcopy(pages)
    log: list[Request] = []

    def fake(endpoint: str, data: Any = None, params: Any = None, **kw: Any) -> Any:
        query = [(k, v) for k, v in (params or {}).items() if k not in _VOLATILE]
        body = list(data.items()) if isinstance(data, dict) else data
        log.append((endpoint, "POST" if data else "GET", body, query))
        result = pages.pop(0) if pages else {}
        client.last_json = result
        return result

    client.private_request = fake  # type: ignore[method-assign]
    return client, log


def _ours(tmp_path: Path, pages: list[dict[str, Any]], **settings: Any) -> tuple[Any, Any]:
    client, log = _rec(pages)
    return _source(tmp_path, client, **settings), log  # type: ignore[arg-type]


def _comment(i: int, at: datetime) -> dict[str, Any]:
    return {
        "pk": str(i),
        "text": f"c{i}",
        "user": {"pk": str(500 + i), "username": f"fan{i}"},
        "created_at_utc": int(at.timestamp()),
        "content_type": "comment",
        "status": "Active",
    }


COMMENT_PAGES = [
    {"comments": [_comment(1, T0)], "has_more_comments": True, "next_max_id": "m1"},
    {"comments": [_comment(2, T0 - timedelta(hours=1))], "has_more_comments": False},
]


def test_comment_pages_have_instagrapis_shape(tmp_path: Path) -> None:
    theirs, expected = _rec(COMMENT_PAGES)
    theirs.media_comments("5_77", amount=200)
    source, got = _ours(tmp_path, COMMENT_PAGES)

    source.get_comments("5_77")

    assert got == expected
    # instagrapi sends the cursor positionally, i.e. as a signed POST body.
    assert [r[1] for r in got] == ["GET", "POST"]


def test_incremental_comment_read_is_a_prefix_of_instagrapis(tmp_path: Path) -> None:
    pages = [
        *COMMENT_PAGES[:1],
        {
            "comments": [_comment(2, T0 - timedelta(hours=2))],
            "has_more_comments": True,
            "next_max_id": "m2",
        },
        {"comments": [_comment(3, T0 - timedelta(hours=3))], "has_more_comments": False},
    ]
    theirs, expected = _rec(pages)
    theirs.media_comments("5_77", amount=200)
    source, got = _ours(tmp_path, pages)

    source.get_comments("5_77", since=T0 - timedelta(hours=1))

    assert got == expected[:2]  # same requests, stopped at the page that is all known


def _users(*pks: int) -> list[dict[str, Any]]:
    return [{"pk": str(pk), "username": f"u{pk}"} for pk in pks]


def _graph_pages() -> list[dict[str, Any]]:
    return [
        {"users": _users(1, 2), "next_max_id": "f1"},  # followers page 1
        {"users": _users(3)},  # followers page 2
        {"users": _users(4), "next_max_id": "g1"},  # following page 1
        {"users": _users(5)},  # following page 2
    ]


def test_follow_list_pages_have_instagrapis_shape(tmp_path: Path) -> None:
    theirs, expected = _rec(_graph_pages())
    theirs.user_followers_v1_chunk("999", 0, order="date_followed_latest")
    theirs.user_following_v1_chunk("999", 0)
    source, got = _ours(tmp_path, _graph_pages())

    graph = source.get_follow_graph()

    assert got == expected
    assert graph == FollowGraph(followers={"1", "2", "3"}, following={"4", "5"})
    assert all(("order", "date_followed_latest") not in r[3] for r in got[2:])  # following


def test_capped_follow_lists_shrink_the_last_page_like_instagrapi(tmp_path: Path) -> None:
    theirs, expected = _rec(_graph_pages())
    theirs.user_followers_v1_chunk("999", 3, order="date_followed_latest")
    theirs.user_following_v1_chunk("999", 3)
    source, got = _ours(tmp_path, _graph_pages(), relationship_fetch_max=3)

    source.get_follow_graph()

    assert got == expected
    assert ("count", 1) in got[1][3]  # 3 - 2 users already read


def test_incremental_followers_then_full_following(tmp_path: Path) -> None:
    pages = [
        {"users": _users(1, 2), "next_max_id": "f1"},  # all known: stop here
        {"users": _users(4), "next_max_id": "g1"},
        {"users": _users(5)},
    ]
    theirs, expected = _rec([pages[0], {"users": []}, *pages[1:]])
    theirs.user_followers_v1_chunk("999", 0, order="date_followed_latest")
    theirs.user_following_v1_chunk("999", 0)
    source, got = _ours(tmp_path, pages)

    graph = source.get_follow_graph(FollowGraph(followers={"1", "2"}, following={"4"}))

    assert got == [expected[0], *expected[2:]]  # followers page 2 skipped, following whole
    assert graph == FollowGraph(followers=set(), following={"4", "5"})


def _thread(n: int, at: datetime) -> dict[str, Any]:
    micros = int(at.timestamp()) * 1_000_000
    return {
        "thread_v2_id": f"v{n}",
        "thread_id": str(340 + n),
        "items": [
            {"item_id": f"i{n}", "user_id": 5, "timestamp": micros, "item_type": "text"},
        ],
        "users": [{"pk": "5", "username": f"u{n}"}],
        "admin_user_ids": [],
        "last_activity_at": micros,
        "muted": False,
        "named": False,
        "canonical": True,
        "pending": False,
        "archived": False,
        "thread_type": "private",
        "thread_title": "",
        "folder": 0,
        "vc_muted": False,
        "is_group": False,
        "mentions_muted": False,
        "approval_required_for_new_members": False,
        "input_mode": 0,
    }


INBOX_PAGES = [
    {"inbox": {"threads": [_thread(1, T0)], "oldest_cursor": "c1"}},
    {"inbox": {"threads": [_thread(2, T0 - timedelta(hours=1))], "oldest_cursor": None}},
]


def test_dm_inbox_pages_have_instagrapis_shape(tmp_path: Path) -> None:
    theirs, expected = _rec(INBOX_PAGES)
    theirs.direct_threads(amount=60)
    source, got = _ours(tmp_path, INBOX_PAGES, dm_threads_limit=60)

    inbox = source.get_dm_threads()

    assert got == expected
    assert [t.thread_id for t in inbox.threads] == ["341", "342"]


def test_media_id_resolution_has_instagrapis_shape(tmp_path: Path) -> None:
    media = {
        "pk": "5",
        "id": "5_77",
        "code": "C5",
        "taken_at": 1700000000,
        "media_type": 1,
        "user": {"pk": "77", "username": "own"},
        "image_versions2": {
            "candidates": [{"url": "https://x.com/a.jpg", "width": 1, "height": 1}]
        },
    }
    pages = [{"items": [media]}, {"users": _users(9)}]
    theirs, expected = _rec(pages)
    theirs.media_likers("5")
    source, got = _ours(tmp_path, pages)

    source.get_likers("5")

    assert got == expected
    assert [r[0] for r in got] == ["media/5/info/", "media/5_77/likers/"]
