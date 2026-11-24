"""Characterization tests for ListUsersUseCase (pinned on the pre-SQL version).

The fixture is built straight through the ORM so every edge the board depends
on is present: engagements interleaved across posts (id order != post order),
two users whose usernames only differ in case (sort ties), a user with two DM
threads (the last one wins), an orphan engagement (no user row), a post
missing from `posts`, a reply exactly at the fiesta cutoff, unicode names.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from app.application.use_cases import ListUsersUseCase, event_counts
from app.domain.traffic_light import TrafficLight
from app.infrastructure.persistence import db, models
from sqlmodel import Session

FIESTA = 1  # promo_start 2026-06-20 12:00 -> cutoff
OTHER = 2
DANGLING = 77  # posts point at it but the event row doesn't exist


def _dt(month: int, day: int, hour: int = 12) -> datetime:
    return datetime(2026, month, day, hour, 0, tzinfo=UTC)


def _seed(session: Session) -> None:
    now = _dt(6, 1)
    session.add_all(
        [
            models.Event(
                id=FIESTA, name="F", promo_start=_dt(6, 20), event_date=_dt(6, 30), created_at=now
            ),
            models.Event(
                id=OTHER, name="O", promo_start=_dt(5, 1), event_date=_dt(5, 30), created_at=now
            ),
        ]
    )
    # "1000" sorts before "300" as text: post order differs from insert order.
    for media_pk, event_id in (("300", FIESTA), ("1000", FIESTA), ("200", None), ("400", OTHER)):
        session.add(
            models.Post(
                media_pk=media_pk,
                shortcode=f"S{media_pk}",
                url=f"https://instagram.com/p/S{media_pk}/",
                event_id=event_id,
            )
        )
    session.add(
        models.Post(media_pk="999", shortcode="S999", url="https://x/p/S999/", event_id=DANGLING)
    )
    users: list[dict[str, Any]] = [
        {
            "pk": "11",
            "username": "zoe",
            "full_name": "ÁNGELES Zoe",
            "follower_count": 500,
            "follows_us": True,
            "we_follow": True,
            "is_verified": True,
        },
        {
            "pk": "12",
            "username": "ana",
            "full_name": "Ana",
            "follows_us": False,
            "is_private": True,
            "biography": "bio",
        },
        {"pk": "13", "username": "dup", "full_name": "Dup Lower", "follower_count": 7},
        {"pk": "14", "username": "DUP", "full_name": "Dup Upper", "follower_count": 7},
        {
            "pk": "15",
            "username": "mia",
            "full_name": "Mía",
            "follower_count": 500,
            "is_business": True,
            "profile_pic_url": "https://pic/mia.jpg",
        },
        {"pk": "16", "username": "bob", "full_name": "", "follower_count": 10, "follows_us": True},
        {"pk": "17", "username": "carl", "full_name": "No Engagement"},
    ]
    for u in users:
        session.add(models.User(first_seen_at=now, last_seen_at=now, **u))
    session.flush()
    engagements = [
        ("15", "300", "like", None, None),
        ("11", "1000", "comment", "hola", _dt(6, 21)),
        ("12", "200", "like", None, None),
        ("14", "300", "like", None, None),
        ("13", "1000", "like", None, None),
        ("11", "300", "like", None, None),
        ("16", "400", "comment", "vamos", _dt(5, 2)),
        ("99", "300", "like", None, None),  # orphan: no user row
        ("16", "1000", "like", None, None),
        ("12", "300", "comment", "cuando?", _dt(6, 25)),
        ("11", "555", "like", None, None),  # post row missing -> post_url None
        ("14", "1000", "like", None, None),
        ("13", "200", "like", None, None),
        ("12", "1000", "like", None, None),
        ("15", "999", "comment", "x", _dt(6, 2)),
    ]
    for i, (user_pk, post_pk, type_, text, created) in enumerate(engagements, 1):
        session.add(
            models.Engagement(
                id=i,
                user_pk=user_pk,
                post_media_pk=post_pk,
                type=type_,
                comment_text=text,
                created_at=created,
            )
        )
    session.flush()
    threads: list[dict[str, Any]] = [
        # zoe: replied before the cutoff, we wrote after it.
        {
            "thread_id": "t-zoe",
            "user_pk": "11",
            "has_outgoing": True,
            "has_incoming": True,
            "last_outgoing_at": _dt(6, 21),
            "last_incoming_at": _dt(6, 10),
            "last_message_at": _dt(6, 21),
        },
        # ana: we wrote before the cutoff only.
        {
            "thread_id": "t-ana",
            "user_pk": "12",
            "has_outgoing": True,
            "has_incoming": False,
            "last_outgoing_at": _dt(6, 1),
            "last_message_at": _dt(6, 1),
        },
        # bob: two threads; the later row must win (it has no messages).
        {
            "thread_id": "t-bob-old",
            "user_pk": "16",
            "has_outgoing": True,
            "has_incoming": True,
            "last_outgoing_at": _dt(6, 22),
            "last_incoming_at": _dt(6, 22),
            "last_message_at": _dt(6, 22),
        },
        {"thread_id": "t-bob-new", "user_pk": "16", "has_outgoing": False, "has_incoming": False},
        # mia: reply exactly at the cutoff (>= counts).
        {
            "thread_id": "t-mia",
            "user_pk": "15",
            "has_outgoing": False,
            "has_incoming": True,
            "last_incoming_at": _dt(6, 20),
            "last_message_at": _dt(6, 20),
        },
        {"thread_id": "t-carl", "user_pk": "17", "has_outgoing": True, "has_incoming": True},
    ]
    for t in threads:
        session.add(models.DmThread(last_synced_at=now, **t))
    session.commit()


@pytest.fixture
def seeded(session: Session) -> Session:
    _seed(session)
    return session


def _names(session: Session, **kwargs: Any) -> list[str]:
    return [v.username for v in ListUsersUseCase(session).execute(**kwargs)]


def _lights(session: Session, **kwargs: Any) -> dict[str, str]:
    return {v.pk: v.traffic_light.value for v in ListUsersUseCase(session).execute(**kwargs)}


def _counts(session: Session, **kwargs: Any) -> tuple[int, int, int, int]:
    c = ListUsersUseCase(session).counts(**kwargs)
    return (c.red, c.yellow, c.green, c.total)


def test_global_full_view(seeded: Session) -> None:
    views = {v.pk: v for v in ListUsersUseCase(seeded).execute()}
    assert set(views) == {"11", "12", "13", "14", "15", "16"}  # carl/orphan excluded

    zoe = views["11"]
    assert zoe.username == "zoe" and zoe.full_name == "ÁNGELES Zoe"
    assert zoe.traffic_light is TrafficLight.GREEN
    assert zoe.thread_id == "t-zoe"
    assert zoe.action_url == "https://instagram.com/direct/t/t-zoe/"
    assert zoe.last_message_at == _dt(6, 21)
    assert zoe.engagement_count == 3
    assert (zoe.follows_us, zoe.we_follow, zoe.follower_count) == (True, True, 500)
    assert (zoe.is_verified, zoe.is_business, zoe.is_private) == (True, False, False)
    assert (zoe.event_engaged, zoe.event_posts_total) == (3, 0)
    assert zoe.last_engaged_at == _dt(6, 21)
    assert [
        (e.post_media_pk, e.type.value, e.comment_text, e.post_url) for e in zoe.engagements
    ] == [
        ("1000", "comment", "hola", "https://instagram.com/p/S1000/"),
        ("300", "like", None, "https://instagram.com/p/S300/"),
        ("555", "like", None, None),
    ]

    ana = views["12"]
    assert ana.traffic_light is TrafficLight.YELLOW
    assert (ana.is_private, ana.biography, ana.follows_us, ana.follower_count) == (
        True,
        "bio",
        False,
        None,
    )
    assert [e.post_media_pk for e in ana.engagements] == ["200", "300", "1000"]
    assert ana.last_engaged_at == _dt(6, 25)

    bob = views["16"]
    assert bob.traffic_light is TrafficLight.RED  # latest thread (no messages) wins
    assert bob.thread_id == "t-bob-new"
    assert bob.last_message_at is None
    assert bob.action_url == "https://instagram.com/direct/t/t-bob-new/"

    dup = views["13"]
    assert dup.thread_id is None
    assert dup.action_url == "https://instagram.com/dup/"
    assert dup.last_engaged_at is None
    assert dup.traffic_light is TrafficLight.RED

    mia = views["15"]
    assert mia.traffic_light is TrafficLight.GREEN
    assert mia.profile_pic_url == "https://pic/mia.jpg" and mia.is_business is True


def test_global_sort_orders(seeded: Session) -> None:
    # Ties (dup/DUP) keep the engagement first-seen order.
    assert _names(seeded) == ["bob", "DUP", "dup", "ana", "mia", "zoe"]
    assert _names(seeded, order="status") == ["bob", "DUP", "dup", "ana", "mia", "zoe"]
    assert _names(seeded, order="username") == ["ana", "bob", "DUP", "dup", "mia", "zoe"]
    assert _names(seeded, order="fans") == ["ana", "zoe", "bob", "DUP", "dup", "mia"]
    assert _names(seeded, order="followers") == ["mia", "zoe", "bob", "DUP", "dup", "ana"]
    assert _names(seeded, order="bogus") == _names(seeded, order="status")


def test_fiesta_view_uses_cutoff_and_post_order(seeded: Session) -> None:
    views = {v.pk: v for v in ListUsersUseCase(seeded).execute(event=FIESTA)}
    assert set(views) == {"11", "12", "13", "14", "15", "16"}
    assert _lights(seeded, event=FIESTA) == {
        "11": "yellow",  # replied before the cutoff, wrote after
        "12": "red",  # wrote before the cutoff
        "13": "red",
        "14": "red",
        "15": "green",  # reply exactly at the cutoff counts
        "16": "red",
    }
    ana = views["12"]
    # Filtered engagements come back post-ordered ("1000" < "300").
    assert [e.post_media_pk for e in ana.engagements] == ["1000", "300"]
    assert (ana.event_engaged, ana.event_posts_total, ana.engagement_count) == (2, 2, 3)
    assert ana.last_engaged_at == _dt(6, 25)
    zoe = views["11"]
    assert [e.post_media_pk for e in zoe.engagements] == ["1000", "300"]
    assert (zoe.event_engaged, zoe.engagement_count) == (2, 3)
    # Tie order flips vs. global: dup's first fiesta engagement is on "1000".
    assert _names(seeded, event=FIESTA) == ["ana", "bob", "dup", "DUP", "zoe", "mia"]
    assert _names(seeded, event=FIESTA, order="fans") == ["ana", "zoe", "bob", "dup", "DUP", "mia"]
    assert _names(seeded, event=FIESTA, order="followers") == [
        "mia",
        "zoe",
        "bob",
        "dup",
        "DUP",
        "ana",
    ]
    assert _names(seeded, event=FIESTA, order="username") == [
        "ana",
        "bob",
        "dup",
        "DUP",
        "mia",
        "zoe",
    ]


def test_other_and_dangling_events(seeded: Session) -> None:
    assert _names(seeded, event=OTHER) == ["bob"]
    assert _lights(seeded, event=OTHER) == {"16": "red"}
    # Event row missing: posts still filter, but lights are global (no cutoff).
    views = ListUsersUseCase(seeded).execute(event=DANGLING)
    assert [(v.username, v.traffic_light.value, v.event_posts_total) for v in views] == [
        ("mia", "green", 1)
    ]
    assert ListUsersUseCase(seeded).execute(event=12345) == []
    assert _counts(seeded, event=12345) == (0, 0, 0, 0)


def test_post_filter(seeded: Session) -> None:
    assert _names(seeded, post="1000") == ["bob", "dup", "DUP", "ana", "zoe"]
    views = ListUsersUseCase(seeded).execute(post="1000")
    assert {v.event_posts_total for v in views} == {0}
    assert {v.event_engaged for v in views} == {1}
    # post + event: cutoff from the event, total counts just the one post.
    both = ListUsersUseCase(seeded).execute(post="300", event=FIESTA)
    assert [(v.username, v.traffic_light.value, v.event_posts_total) for v in both] == [
        ("ana", "red", 1),
        ("DUP", "red", 1),
        ("zoe", "yellow", 1),
        ("mia", "green", 1),
    ]
    assert ListUsersUseCase(seeded).execute(post="nope") == []


def test_status_search_follows_filters(seeded: Session) -> None:
    assert _names(seeded, status=TrafficLight.RED) == ["bob", "DUP", "dup"]
    assert _names(seeded, status=TrafficLight.YELLOW) == ["ana"]
    assert _names(seeded, status=TrafficLight.GREEN) == ["mia", "zoe"]
    assert _names(seeded, event=FIESTA, status=TrafficLight.YELLOW) == ["zoe"]
    # Search is case-insensitive over username and full name, unicode included.
    assert _names(seeded, search="ángeles") == ["zoe"]
    assert _names(seeded, search="DUP") == ["DUP", "dup"]
    assert _names(seeded, search="upper") == ["DUP"]
    assert _names(seeded, search="í") == ["mia"]
    assert _names(seeded, search="MÍA") == ["mia"]  # needle folded with str.lower
    assert _names(seeded, search="") == _names(seeded)
    assert _names(seeded, search="zzz") == []
    # follows=True keeps only followers; False/None don't filter.
    assert _names(seeded, follows=True) == ["bob", "zoe"]
    assert _names(seeded, follows=False) == _names(seeded)
    assert _names(seeded, event=FIESTA, follows=True, search="o") == ["bob", "zoe"]


def test_pagination_edges(seeded: Session) -> None:
    full = _names(seeded, order="username")
    assert _names(seeded, order="username", limit=2) == full[:2]
    assert _names(seeded, order="username", limit=2, offset=2) == full[2:4]
    assert _names(seeded, order="username", offset=4) == full[4:]
    assert _names(seeded, order="username", offset=6) == []
    assert _names(seeded, order="username", offset=100, limit=5) == []
    assert _names(seeded, order="username", limit=100) == full
    assert _names(seeded, order="fans", limit=3, offset=1) == _names(seeded, order="fans")[1:4]
    page = ListUsersUseCase(seeded).execute(event=FIESTA, limit=2, offset=2)
    assert [v.username for v in page] == ["dup", "DUP"]
    assert [e.post_media_pk for e in page[1].engagements] == ["1000", "300"]


def test_users_endpoint_pages_with_limit_and_offset(seeded: Session) -> None:
    from app.api.routers.users import list_users

    def page(limit: int | None, offset: int) -> list[str]:
        out = list_users(
            event=FIESTA,
            post=None,
            status=None,
            search=None,
            order="status",
            follows=None,
            limit=limit,
            offset=offset,
            session=seeded,
        )
        return [u.username for u in out]

    full = _names(seeded, event=FIESTA)
    assert page(None, 0) == full
    assert page(2, 0) + page(2, 2) + page(2, 4) == full
    assert page(2, 6) == []


def test_counts(seeded: Session) -> None:
    assert _counts(seeded) == (3, 1, 2, 6)
    assert _counts(seeded, event=FIESTA) == (4, 1, 1, 6)
    assert _counts(seeded, event=FIESTA, follows=True) == (1, 1, 0, 2)
    assert _counts(seeded, search="dup") == (2, 0, 0, 2)
    assert _counts(seeded, post="1000") == (3, 1, 1, 5)
    c = event_counts(seeded, FIESTA)
    assert (c.red, c.yellow, c.green, c.total) == (4, 1, 1, 6)


def test_empty_db(session: Session) -> None:
    assert ListUsersUseCase(session).execute() == []
    assert _counts(session) == (0, 0, 0, 0)


def test_py_lower_registered_on_every_pooled_connection(tmp_path: Any) -> None:
    """S14: unicode-aware search works on every pooled/new file-DB connection."""
    import threading

    now = _dt(11, 1)
    eng = db.build_engine(f"sqlite:///{tmp_path / 'p.db'}")
    db.create_db_and_tables(eng)
    with Session(eng) as s:
        s.add(models.User(pk="1", username="Ángeles", first_seen_at=now, last_seen_at=now))
        s.add(models.Post(media_pk="p", shortcode="p", url="u"))
        s.flush()
        s.add(models.Engagement(user_pk="1", post_media_pk="p", type="like"))
        s.commit()

    errors: list[str] = []

    def run() -> None:
        try:
            for _ in range(10):
                with Session(eng) as s:
                    assert [v.pk for v in ListUsersUseCase(s).execute(search="ÁN")] == ["1"]
        except Exception as exc:  # noqa: BLE001 — surfaced through `errors`
            errors.append(repr(exc))

    threads = [threading.Thread(target=run) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    with Session(eng) as s:
        s.connection().invalidate()
    with Session(eng) as s:
        assert ListUsersUseCase(s).counts(search="án").total == 1
    eng.dispose()
    assert errors == []
