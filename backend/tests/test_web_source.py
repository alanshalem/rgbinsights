"""Unit tests for the pure parsing helpers of WebInstagramSource.

No network: we feed sample payloads shaped like the web API responses and
assert the domain mapping, including DM direction.
"""

from __future__ import annotations

from app.infrastructure.instagram.web_source import (
    extract_shortcode,
    parse_comments,
    parse_inbox,
    parse_likers,
    parse_media_info,
    pk_from_sessionid,
    shortcode_to_pk,
)


def test_extract_shortcode() -> None:
    assert extract_shortcode("https://www.instagram.com/p/DZ_FScuPpe8/") == "DZ_FScuPpe8"
    assert extract_shortcode("https://instagram.com/reel/ABC123/?x=1") == "ABC123"
    assert extract_shortcode("https://instagram.com/rgb.collective___/") is None


def test_shortcode_to_pk_roundtrip_known() -> None:
    # Known mapping: shortcode "B" -> 1 (index of 'B' in the alphabet).
    assert shortcode_to_pk("B") == 1
    assert shortcode_to_pk("AAAB") == 1


def test_pk_from_sessionid_handles_encoded_colons() -> None:
    assert pk_from_sessionid("70564260578%3APOvOk%3A22%3AAYj") == "70564260578"
    assert pk_from_sessionid("123:abc:def") == "123"


def test_parse_media_info() -> None:
    data = {
        "items": [
            {"pk": "900", "code": "Cabc", "caption": {"text": "hola"}, "taken_at": 1749000000}
        ]
    }
    post = parse_media_info(data)
    assert post.media_pk == "900"
    assert post.shortcode == "Cabc"
    assert post.caption == "hola"
    assert post.taken_at is not None


def test_parse_comments_and_likers() -> None:
    comments = parse_comments(
        {"comments": [{"user": {"pk": "1", "username": "lucia"}, "text": "temazo"}]}
    )
    assert comments[0].user.username == "lucia"
    assert comments[0].text == "temazo"

    likers = parse_likers({"users": [{"pk": "2", "username": "tomas"}]})
    assert [u.username for u in likers] == ["tomas"]


def test_parse_inbox_direction() -> None:
    our_pk = "100"
    data = {
        "inbox": {
            "threads": [
                {  # they replied -> incoming present
                    "thread_id": "t1",
                    "users": [{"pk": "200", "username": "lucia"}],
                    "items": [
                        {"user_id": 100, "timestamp": 1749000000000000},
                        {"user_id": 200, "timestamp": 1749000100000000},
                    ],
                },
                {  # we wrote only -> outgoing only
                    "thread_id": "t2",
                    "users": [{"pk": "300", "username": "tomas"}],
                    "items": [{"user_id": 100, "timestamp": 1749000000000000}],
                },
                {  # group thread -> skipped
                    "thread_id": "t3",
                    "users": [{"pk": "400"}, {"pk": "500"}],
                    "items": [],
                },
            ]
        }
    }
    threads = parse_inbox(data, our_pk)
    assert {t.thread_id for t in threads} == {"t1", "t2"}

    lucia = next(t for t in threads if t.thread_id == "t1")
    assert any(m.user_pk == our_pk for m in lucia.messages)  # outgoing
    assert any(m.user_pk != our_pk for m in lucia.messages)  # incoming

    tomas = next(t for t in threads if t.thread_id == "t2")
    assert all(m.user_pk == our_pk for m in tomas.messages)  # outgoing only
