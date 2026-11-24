from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from app.application.use_cases import (
    KEY_RELATIONS_SYNCED,
    EnrichProfilesUseCase,
    ListUsersUseCase,
    ScanPostsUseCase,
    ScanPostUseCase,
    SyncDmsUseCase,
)
from app.domain.entities import IgUser, ProfileInfo
from app.domain.result import Err, ErrorCode, Ok
from app.domain.traffic_light import TrafficLight
from app.infrastructure.instagram.base import FollowGraph
from app.infrastructure.instagram.errors import RateLimitedError
from app.infrastructure.instagram.fake_source import FakeInstagramSource
from app.infrastructure.persistence import db, models
from app.infrastructure.persistence.repositories import AppStateRepository, UserRepository
from sqlalchemy.engine import Engine
from sqlmodel import Session, col, select

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

    # Just scanned, so a plain rescan skips it (cache: skip-if-recent).
    cached = RescanEventUseCase(source, session, recent_limit=50).execute(event.id)
    assert isinstance(cached, Ok)
    assert cached.value.results == []
    assert cached.value.skipped == 1

    # force=True re-scans regardless of freshness.
    forced = RescanEventUseCase(source, session, recent_limit=50).execute(event.id, force=True)
    assert isinstance(forced, Ok)
    assert len(forced.value.results) == 1  # the one post assigned to the fiesta


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
    from app.application.use_cases import EnrichProfilesUseCase
    from app.infrastructure.persistence.repositories import UserRepository

    source = FakeInstagramSource()
    ScanPostUseCase(source, session).execute(POST_A_URL)
    ScanPostUseCase(source, session).execute("https://instagram.com/p/Cdef456/")
    # Follow status now comes from the enrich step, not the DM sync.
    EnrichProfilesUseCase(source, session).execute(UserRepository(session).all_pks())

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


def test_sync_dms_is_incremental_after_first(session: Session) -> None:
    source = FakeInstagramSource()
    first = SyncDmsUseCase(source, session).execute()
    assert isinstance(first, Ok)
    assert first.value.incremental is False  # no prior sync -> full pull

    second = SyncDmsUseCase(source, session).execute()
    assert isinstance(second, Ok)
    assert second.value.incremental is True  # only changes since last time


def test_enrich_relationships_cached_within_ttl(session: Session) -> None:
    source = FakeInstagramSource()
    ScanPostUseCase(source, session).execute(POST_A_URL)
    pks = [u.pk for u in ListUsersUseCase(session).execute()]

    first = EnrichProfilesUseCase(source, session).execute(pks, cache_hours=12)
    assert isinstance(first, Ok)
    assert first.value.relations_cached is False
    assert first.value.relations > 0

    second = EnrichProfilesUseCase(source, session).execute(pks, cache_hours=12)
    assert isinstance(second, Ok)
    assert second.value.relations_cached is True  # fresh -> followers fetch skipped

    forced = EnrichProfilesUseCase(source, session).execute(pks, cache_hours=12, force=True)
    assert isinstance(forced, Ok)
    assert forced.value.relations_cached is False  # force bypasses the cache


# -- S8 + S9: enrich saves in batches, caps, incremental follow graph ------------

ENRICH_NOW = datetime(2026, 11, 24, 15, 0, tzinfo=UTC)  # 12:00 in Argentina
AR = timezone(timedelta(hours=-3))


class EnrichSource(FakeInstagramSource):
    """Fake source for enrich: records calls, can fail at the N-th profile read and
    probes that no SQLite write lock is held while it "talks to Instagram"."""

    def __init__(self, fail_at: int | None = None, db_path: Path | None = None) -> None:
        super().__init__()
        self.fail_at = fail_at
        self.db_path = db_path
        self.profile_calls: list[str] = []
        self.graph_calls: list[FollowGraph | None] = []
        self.locked_during_ig: list[str] = []
        self.followers = {"101", "102"}
        self.following = {"102"}

    def _probe_write_lock(self, what: str) -> None:
        if self.db_path is None:
            return
        other = sqlite3.connect(self.db_path, timeout=0)
        try:
            other.execute("BEGIN IMMEDIATE")
            other.execute("ROLLBACK")
        except sqlite3.OperationalError:
            self.locked_during_ig.append(what)
        finally:
            other.close()

    def get_follow_graph(self, known: FollowGraph | None = None) -> FollowGraph:
        self._probe_write_lock("graph")
        self.graph_calls.append(known)
        if known is None:
            return FollowGraph(followers=set(self.followers), following=set(self.following))
        # New followers only; following is always read whole (no reliable order).
        return FollowGraph(
            followers=self.followers - known.followers, following=set(self.following)
        )

    def get_profile(self, username: str) -> ProfileInfo:
        self._probe_write_lock(username)
        self.profile_calls.append(username)
        if self.fail_at is not None and len(self.profile_calls) == self.fail_at:
            raise RateLimitedError("Se alcanzó el tope de seguridad de 200 pedidos por hora.")
        return super().get_profile(username)


def _file_engine(tmp_path: Path) -> tuple[Engine, Path]:
    path = tmp_path / "enrich.db"
    engine = db.build_engine(f"sqlite:///{path}")
    db.create_db_and_tables(engine)
    return engine, path


def _seed_users(session: Session, count: int) -> list[str]:
    users = [IgUser(pk=str(101 + i), username=f"user{101 + i}") for i in range(count)]
    UserRepository(session).upsert_many(users, ENRICH_NOW)
    session.commit()
    return [u.pk for u in users]


def _synced(engine: Engine) -> int:
    with Session(engine) as fresh:
        rows = fresh.exec(
            select(models.User).where(col(models.User.profile_synced_at).is_not(None))
        )
        return len(list(rows))


@pytest.fixture
def at_noon(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.application.use_cases.enrich._now", lambda: ENRICH_NOW)


@pytest.mark.usefixtures("at_noon")
def test_enrich_failure_keeps_fetched_profiles_and_resumes(tmp_path: Path) -> None:
    engine, _ = _file_engine(tmp_path)
    try:
        with Session(engine) as session:
            pks = _seed_users(session, 25)
            source = EnrichSource(fail_at=13)
            result = EnrichProfilesUseCase(source, session).execute(pks)

        assert isinstance(result, Err)
        assert result.code is ErrorCode.RATE_LIMITED
        assert "Se guardaron 12 perfiles; faltan 13" in result.message
        assert _synced(engine) == 12  # committed, visible to another connection
        with Session(engine) as fresh:
            lucia = fresh.get(models.User, "101")
            assert lucia is not None and lucia.follows_us is True  # graph saved before profiles
            assert AppStateRepository(fresh).get_dt(KEY_RELATIONS_SYNCED) is not None

        with Session(engine) as session:
            again = EnrichSource()
            second = EnrichProfilesUseCase(again, session).execute(pks)

        assert isinstance(second, Ok)
        assert second.value.enriched == 13
        assert again.profile_calls == [f"user{101 + i}" for i in range(12, 25)]  # only the rest
        assert again.graph_calls == []  # relationships still fresh
        assert _synced(engine) == 25
    finally:
        engine.dispose()


@pytest.mark.usefixtures("at_noon")
def test_enrich_holds_no_write_lock_while_calling_instagram(tmp_path: Path) -> None:
    engine, path = _file_engine(tmp_path)
    try:
        with Session(engine) as session:
            pks = _seed_users(session, 23)
            source = EnrichSource(db_path=path)
            result = EnrichProfilesUseCase(source, session).execute(pks)

        assert isinstance(result, Ok)
        assert len(source.profile_calls) == 23
        assert source.locked_during_ig == []
    finally:
        engine.dispose()


@pytest.mark.usefixtures("at_noon")
def test_enrich_per_run_and_per_day_caps(session: Session) -> None:
    pks = _seed_users(session, 10)
    repo = UserRepository(session)
    for pk, synced in (
        ("900", datetime(2026, 11, 24, 2, 0, tzinfo=UTC)),  # 23:00 of the 23rd in AR
        ("901", datetime(2026, 11, 24, 4, 0, tzinfo=UTC)),  # 01:00 of the 24th in AR
    ):
        repo.upsert_many([IgUser(pk=pk, username=f"old{pk}")], ENRICH_NOW)
        session.flush()
        repo.set_profile(pk, FakeInstagramSource().get_profile(f"old{pk}"), synced)
    session.commit()

    def run() -> list[str]:
        source = EnrichSource()
        result = EnrichProfilesUseCase(source, session).execute(pks, limit=4, daily_cap=6, tz=AR)
        assert isinstance(result, Ok)
        return source.profile_calls

    assert len(run()) == 4  # per-run cap
    assert len(run()) == 1  # 6 a day: 01:00 AR one + 4 + this one
    assert run() == []  # daily cap reached: zero profile requests


def test_enrich_reads_the_follow_graph_incrementally(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = [ENRICH_NOW]
    monkeypatch.setattr("app.application.use_cases.enrich._now", lambda: now[0])
    pks = _seed_users(session, 3)  # 101, 102, 103
    source = EnrichSource()

    def run(**kwargs: Any) -> dict[str, bool | None]:
        result = EnrichProfilesUseCase(source, session).execute(
            pks, cache_hours=0, full_refresh_days=7, **kwargs
        )
        assert isinstance(result, Ok)
        return {pk: u.follows_us for pk in pks if (u := session.get(models.User, pk))}

    assert run() == {"101": True, "102": True, "103": False}
    assert source.graph_calls == [None]  # first read: full

    source.followers = {"101", "102", "103"}  # 103 followed us
    source.followers.discard("101")  # ...and 101 unfollowed
    source.following = set()  # we unfollowed 102
    assert run() == {"101": True, "102": True, "103": True}  # incremental only adds
    assert source.graph_calls[-1] == FollowGraph(followers={"101", "102"}, following={"102"})
    tomas = session.get(models.User, "102")
    assert tomas is not None and tomas.we_follow is False  # following is always whole

    now[0] = ENRICH_NOW + timedelta(days=8)  # past the full-refresh period
    assert run() == {"101": False, "102": True, "103": True}
    assert source.graph_calls[-1] is None

    source.followers.discard("102")
    assert run(force=True)["102"] is False  # force = full read
    assert source.graph_calls[-1] is None
