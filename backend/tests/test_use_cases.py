from __future__ import annotations

from datetime import UTC, datetime

from app.application.use_cases import (
    ListUsersUseCase,
    ScanPostsUseCase,
    ScanPostUseCase,
    SyncDmsUseCase,
)
from app.domain.result import Err, ErrorCode, Ok
from app.domain.traffic_light import TrafficLight
from app.infrastructure.instagram.fake_source import FakeInstagramSource
from sqlmodel import Session

POST_A_URL = "https://instagram.com/p/Cabc123/"


def _scan_and_sync(session: Session) -> None:
    source = FakeInstagramSource()
    # Scan both posts so every fake user lands in the DB.
    ScanPostUseCase(source, session).execute(POST_A_URL)
    ScanPostUseCase(source, session).execute("https://instagram.com/p/Cdef456/")
    SyncDmsUseCase(source, session).execute()


def test_scan_post_counts_users(session: Session) -> None:
    result = ScanPostUseCase(FakeInstagramSource(), session).execute(POST_A_URL)
    assert isinstance(result, Ok)
    # post A: comments lucia+sofia, likers tomas+sofia+martin -> 4 unique
    assert result.value.users_found == 4
    assert result.value.new_users == 4


def test_scan_post_is_idempotent(session: Session) -> None:
    source = FakeInstagramSource()
    ScanPostUseCase(source, session).execute(POST_A_URL)
    second = ScanPostUseCase(source, session).execute(POST_A_URL)
    assert isinstance(second, Ok)
    # Same users, but re-scan adds no *new* users and no duplicate rows.
    assert second.value.new_users == 0

    from app.infrastructure.persistence import models
    from sqlmodel import select

    engagements = list(session.exec(select(models.Engagement)))
    # 2 comments + 3 likes, unique per (user, post, type). sofia has both.
    assert len(engagements) == 5


def test_scan_post_not_found(session: Session) -> None:
    result = ScanPostUseCase(FakeInstagramSource(), session).execute("https://x/p/nope/")
    assert isinstance(result, Err)
    assert result.code is ErrorCode.POST_NOT_FOUND


def test_traffic_light_states(session: Session) -> None:
    _scan_and_sync(session)
    views = {v.username: v for v in ListUsersUseCase(session).execute()}

    assert views["lucia.dj"].traffic_light is TrafficLight.GREEN  # answered
    assert views["tomas_beats"].traffic_light is TrafficLight.YELLOW  # no reply
    assert views["sofi.raver"].traffic_light is TrafficLight.RED  # no thread
    assert views["martin.k"].traffic_light is TrafficLight.RED  # no thread


def test_action_url_dm_vs_profile(session: Session) -> None:
    _scan_and_sync(session)
    views = {v.username: v for v in ListUsersUseCase(session).execute()}

    assert "/direct/t/t-lucia/" in views["lucia.dj"].action_url  # has thread
    assert views["sofi.raver"].action_url.endswith("/sofi.raver/")  # profile fallback


def test_filter_by_status_and_post(session: Session) -> None:
    _scan_and_sync(session)
    reds = ListUsersUseCase(session).execute(status=TrafficLight.RED)
    assert {v.username for v in reds} == {"sofi.raver", "martin.k"}

    only_b = ListUsersUseCase(session).execute(post="900002")
    assert {v.username for v in only_b} == {"lucia.dj", "tomas_beats"}


def test_scan_assigns_event(session: Session) -> None:
    from app.infrastructure.persistence import models
    from app.infrastructure.persistence.repositories import EventRepository, PostRepository

    event = EventRepository(session).create(
        models.Event(
            name="Fiesta test",
            promo_start=datetime(2026, 6, 1, tzinfo=UTC),
            event_date=datetime(2026, 6, 30, tzinfo=UTC),
            created_at=datetime(2026, 6, 1, tzinfo=UTC),
        )
    )
    source = FakeInstagramSource()
    ScanPostUseCase(source, session).execute(POST_A_URL, event_id=event.id)

    posts = PostRepository(session)
    assert posts.get("900001") is not None
    assert posts.get("900001").event_id == event.id  # type: ignore[union-attr]
    assert {p.media_pk for p in posts.list_all(event_id=event.id)} == {"900001"}
    assert posts.list_all(event_id=999) == []


def test_rescan_event(session: Session) -> None:
    from app.application.use_cases import RescanEventUseCase
    from app.infrastructure.persistence import models
    from app.infrastructure.persistence.repositories import EventRepository

    event = EventRepository(session).create(
        models.Event(
            name="Fiesta",
            promo_start=datetime(2026, 6, 1, tzinfo=UTC),
            event_date=datetime(2026, 6, 30, tzinfo=UTC),
            created_at=datetime(2026, 6, 1, tzinfo=UTC),
        )
    )
    source = FakeInstagramSource()
    assert event.id is not None
    ScanPostUseCase(source, session).execute(POST_A_URL, event_id=event.id)

    result = RescanEventUseCase(source, session, recent_limit=50).execute(event.id)
    assert isinstance(result, Ok)
    assert len(result.value.results) == 1  # the one post assigned to the fiesta


def test_semaforo_per_fiesta_cutoff(session: Session) -> None:
    from app.infrastructure.persistence import models
    from app.infrastructure.persistence.repositories import EventRepository

    # lucia replied on Jun 13 (fake data). Fiesta campaign starts Jun 20 -> her
    # old reply must NOT count for this fiesta.
    event = EventRepository(session).create(
        models.Event(
            name="Fiesta nueva",
            promo_start=datetime(2026, 6, 20, tzinfo=UTC),
            event_date=datetime(2026, 6, 25, tzinfo=UTC),
            created_at=datetime(2026, 6, 20, tzinfo=UTC),
        )
    )
    source = FakeInstagramSource()
    ScanPostUseCase(source, session).execute(POST_A_URL, event_id=event.id)
    SyncDmsUseCase(source, session).execute()

    global_views = {v.username: v for v in ListUsersUseCase(session).execute()}
    assert global_views["lucia.dj"].traffic_light is TrafficLight.GREEN  # ever talked

    fiesta_views = {v.username: v for v in ListUsersUseCase(session).execute(event=event.id)}
    assert fiesta_views["lucia.dj"].traffic_light is TrafficLight.RED  # not since Jun 20

    counts = ListUsersUseCase(session).counts(event=event.id)
    assert counts.total == len(fiesta_views)


def test_follow_status_synced_and_filtered(session: Session) -> None:
    source = FakeInstagramSource()
    ScanPostUseCase(source, session).execute(POST_A_URL)
    ScanPostUseCase(source, session).execute("https://instagram.com/p/Cdef456/")
    SyncDmsUseCase(source, session).execute()  # also fills follow status

    views = {v.username: v for v in ListUsersUseCase(session).execute()}
    assert views["lucia.dj"].follows_us is True
    assert views["tomas_beats"].follows_us is True and views["tomas_beats"].we_follow is True
    assert views["sofi.raver"].follows_us is False

    followers = {v.username for v in ListUsersUseCase(session).execute(follows=True)}
    assert "lucia.dj" in followers  # follows us
    assert "sofi.raver" not in followers  # doesn't


def test_scan_by_date_range(session: Session) -> None:
    source = FakeInstagramSource()
    use_case = ScanPostsUseCase(source, session, recent_limit=50)
    result = use_case.by_date_range(
        datetime(2026, 6, 1, tzinfo=UTC),
        datetime(2026, 6, 15, tzinfo=UTC),
    )
    assert isinstance(result, Ok)
    # Only post A (taken_at Jun 10) falls in range; post B is Jun 20.
    assert len(result.value.results) == 1
    assert result.value.results[0].post.shortcode == "Cabc123"
