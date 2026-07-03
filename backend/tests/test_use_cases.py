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
