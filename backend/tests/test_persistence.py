"""Persistence: upsert semantics (characterization), query counts, SQLite setup."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from app.application.use_cases import KEY_DMS_SYNCED, ScanPostUseCase, SyncDmsUseCase
from app.domain.entities import Comment, DmMessage, DmThread, IgUser, Post
from app.domain.result import Ok
from app.infrastructure.instagram.fake_source import FakeInstagramSource
from app.infrastructure.persistence import db, models
from app.infrastructure.persistence.repositories import AppStateRepository, EventRepository
from sqlalchemy import event, text
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, col, select

OUR_PK = "0"
POST = Post(media_pk="555", shortcode="Sx", url="https://instagram.com/p/Sx/", caption="c")
T1 = datetime(2026, 6, 1, 10, 0, tzinfo=UTC)
T2 = datetime(2026, 6, 2, 10, 0, tzinfo=UTC)


class ScriptedSource(FakeInstagramSource):
    """Returns whatever the test sets; never touches Instagram."""

    def __init__(self) -> None:
        super().__init__()
        self.comments: list[Comment] = []
        self.likers: list[IgUser] = []
        self.threads: list[DmThread] = []

    def get_post(self, url: str) -> Post:
        return POST

    def get_comments(self, media_pk: str) -> list[Comment]:
        return list(self.comments)

    def get_likers(self, media_pk: str) -> list[IgUser]:
        return list(self.likers)

    def get_dm_threads(
        self, progress: object | None = None, since: datetime | None = None
    ) -> list[DmThread]:
        return list(self.threads)


def _at(monkeypatch: pytest.MonkeyPatch, when: datetime) -> None:
    monkeypatch.setattr("app.application.use_cases.scan._now", lambda: when)
    monkeypatch.setattr("app.application.use_cases.sync._now", lambda: when)


def _users(session: Session) -> list[tuple[Any, ...]]:
    rows = session.exec(text("SELECT pk FROM users ORDER BY rowid")).all()  # type: ignore[call-overload]
    out = []
    for (pk,) in rows:
        u = session.get(models.User, pk)
        assert u is not None
        out.append(
            (
                u.pk,
                u.username,
                u.full_name,
                u.profile_pic_url,
                u.is_private,
                u.first_seen_at,
                u.last_seen_at,
                u.follows_us,
                u.follower_count,
            )
        )
    return out


def _engagements(session: Session) -> list[tuple[Any, ...]]:
    rows = session.exec(select(models.Engagement).order_by(col(models.Engagement.id)))
    return [(e.user_pk, e.post_media_pk, e.type, e.comment_text, e.created_at) for e in rows]


def _threads(session: Session) -> list[tuple[Any, ...]]:
    rows = session.exec(text("SELECT thread_id FROM dm_threads ORDER BY rowid")).all()  # type: ignore[call-overload]
    out = []
    for (thread_id,) in rows:
        t = session.get(models.DmThread, thread_id)
        assert t is not None
        out.append(
            (
                t.thread_id,
                t.user_pk,
                t.has_outgoing,
                t.has_incoming,
                t.last_outgoing_at,
                t.last_incoming_at,
                t.last_message_at,
                t.last_synced_at,
            )
        )
    return out


A1 = IgUser(pk="1", username="ana", full_name="Ana", profile_pic_url="p1", is_private=False)
A2 = IgUser(pk="1", username="ana", full_name="Ana B", profile_pic_url="p2", is_private=True)
A3 = IgUser(pk="1", username="ana.new", full_name="Ana C", profile_pic_url=None)
B = IgUser(pk="2", username="beto", full_name="Beto")
C = IgUser(pk="3", username="caro")
D = IgUser(pk="4", username="dani")


# -- characterization: scan upserts --------------------------------------------


def test_scan_user_upsert_semantics(session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    src = ScriptedSource()
    src.comments = [Comment(user=A1, text="hola"), Comment(user=B, text="yo")]
    src.likers = [A2, C]  # A appears twice: the later (liker) data wins
    _at(monkeypatch, T1)
    first = ScanPostUseCase(src, session).execute(POST.url)
    assert isinstance(first, Ok)
    assert (first.value.users_found, first.value.new_users) == (3, 3)
    assert _users(session) == [
        ("1", "ana", "Ana B", "p2", True, T1, T1, None, None),
        ("2", "beto", "Beto", None, False, T1, T1, None, None),
        ("3", "caro", "", None, False, T1, T1, None, None),
    ]

    # Enrich-owned fields must survive a re-scan.
    ana = session.get(models.User, "1")
    assert ana is not None
    ana.follows_us, ana.follower_count = True, 42
    session.add(ana)
    session.commit()

    src.comments = []
    src.likers = [D, A3]
    _at(monkeypatch, T2)
    second = ScanPostUseCase(src, session).execute(POST.url)
    assert isinstance(second, Ok)
    assert (second.value.users_found, second.value.new_users) == (2, 1)
    assert _users(session) == [
        ("1", "ana.new", "Ana C", None, False, T1, T2, True, 42),
        ("2", "beto", "Beto", None, False, T1, T1, None, None),
        ("3", "caro", "", None, False, T1, T1, None, None),
        ("4", "dani", "", None, False, T2, T2, None, None),
    ]


def test_scan_engagement_upsert_semantics(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    c1 = datetime(2026, 6, 1, 9, 0, tzinfo=UTC)
    c2 = datetime(2026, 6, 1, 9, 30, tzinfo=UTC)
    src = ScriptedSource()
    # Same user commenting twice + liking twice: one row per (user, post, type).
    src.comments = [
        Comment(user=A1, text="one", created_at=c1),
        Comment(user=B, text="x", created_at=c1),
        Comment(user=A1, text="two", created_at=c2),
    ]
    src.likers = [A1, C, A1]
    _at(monkeypatch, T1)
    ScanPostUseCase(src, session).execute(POST.url)
    assert _engagements(session) == [
        ("1", "555", "comment", "two", c1),  # last text, first created_at
        ("2", "555", "comment", "x", c1),
        ("1", "555", "like", None, None),
        ("3", "555", "like", None, None),
    ]

    src.comments = [
        Comment(user=A1, text="edited", created_at=c2),
        Comment(user=B, text="", created_at=c2),  # "" is not None -> overwrites
        Comment(user=D, text="new", created_at=c2),
    ]
    src.likers = [C, B]
    _at(monkeypatch, T2)
    ScanPostUseCase(src, session).execute(POST.url)
    assert _engagements(session) == [
        ("1", "555", "comment", "edited", c1),
        ("2", "555", "comment", "", c1),
        ("1", "555", "like", None, None),
        ("3", "555", "like", None, None),
        ("4", "555", "comment", "new", c2),
        ("2", "555", "like", None, None),
    ]
    post = session.get(models.Post, "555")
    assert post is not None and post.last_scanned_at == T2


# -- characterization: DM sync upserts -----------------------------------------


def _thread(thread_id: str, user: IgUser, out: list[int], inc: list[int]) -> DmThread:
    def at(h: int) -> datetime:
        return datetime(2026, 6, 1, h, 0, tzinfo=UTC)

    msgs = [DmMessage(user_pk=OUR_PK, created_at=at(h)) for h in out]
    msgs += [DmMessage(user_pk=user.pk, created_at=at(h)) for h in inc]
    last = max(out + inc) if out or inc else None
    return DmThread(
        thread_id=thread_id,
        user=user,
        messages=msgs,
        last_message_at=at(last) if last is not None else None,
    )


def _h(h: int) -> datetime:
    return datetime(2026, 6, 1, h, 0, tzinfo=UTC)


def test_sync_thread_upsert_semantics(session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    src = ScriptedSource()
    src.threads = [
        _thread("t1", A1, out=[1, 3], inc=[2]),
        _thread("t2", B, out=[4], inc=[]),
        _thread("t1", A2, out=[5], inc=[]),  # same thread twice: the later wins
    ]
    _at(monkeypatch, T1)
    first = SyncDmsUseCase(src, session).execute()
    assert isinstance(first, Ok)
    assert (first.value.threads_synced, first.value.users_touched) == (3, 3)
    assert _threads(session) == [
        ("t1", "1", True, False, _h(5), None, _h(5), T1),
        ("t2", "2", True, False, _h(4), None, _h(4), T1),
    ]
    assert _users(session) == [
        ("1", "ana", "Ana B", "p2", True, T1, T1, None, None),
        ("2", "beto", "Beto", None, False, T1, T1, None, None),
    ]

    src.threads = [_thread("t1", C, out=[], inc=[6]), _thread("t3", D, out=[], inc=[])]
    _at(monkeypatch, T2)
    SyncDmsUseCase(src, session).execute()
    assert _threads(session) == [
        ("t1", "3", False, True, None, _h(6), _h(6), T2),  # every field overwritten
        ("t2", "2", True, False, _h(4), None, _h(4), T1),  # untouched
        ("t3", "4", False, False, None, None, None, T2),
    ]
    assert [u[0] for u in _users(session)] == ["1", "2", "3", "4"]
    assert AppStateRepository(session).get_dt(KEY_DMS_SYNCED) == T2


# -- query counts (S13) ---------------------------------------------------------


@contextmanager
def _count_statements(session: Session) -> Iterator[list[str]]:
    bind = session.get_bind()
    assert isinstance(bind, Engine)
    seen: list[str] = []

    def on_execute(*args: Any) -> None:
        seen.append(args[2])

    event.listen(bind, "before_cursor_execute", on_execute)
    try:
        yield seen
    finally:
        event.remove(bind, "before_cursor_execute", on_execute)


def test_scan_1000_likers_uses_batched_statements(session: Session) -> None:
    src = ScriptedSource()
    src.likers = [IgUser(pk=str(10_000 + i), username=f"u{i}") for i in range(1000)]
    src.comments = [Comment(user=src.likers[i], text=f"c{i}") for i in range(0, 1000, 2)]
    with _count_statements(session) as first:
        ScanPostUseCase(src, session).execute(POST.url)
    with _count_statements(session) as second:
        result = ScanPostUseCase(src, session).execute(POST.url)
    assert isinstance(result, Ok) and result.value.users_found == 1000
    assert len(_engagements(session)) == 1500
    # O(batches), not O(rows): a handful of SELECT ... IN / bulk statements.
    assert len(first) <= 20, len(first)
    assert len(second) <= 20, len(second)


def test_sync_many_threads_uses_batched_statements(session: Session) -> None:
    src = ScriptedSource()
    src.threads = [
        _thread(f"t{i}", IgUser(pk=str(i), username=f"u{i}"), out=[1], inc=[2] if i % 2 else [])
        for i in range(1, 1001)
    ]
    with _count_statements(session) as first:
        SyncDmsUseCase(src, session).execute()
    with _count_statements(session) as second:
        SyncDmsUseCase(src, session).execute()
    assert len(_threads(session)) == 1000
    assert len(first) <= 20, len(first)
    assert len(second) <= 20, len(second)


# -- events aggregates (S14) ------------------------------------------------------


def test_event_post_counts_and_last_scanned(session: Session) -> None:
    for media_pk, event_id, scanned in (
        ("a", 1, T1),
        ("b", 1, T2),
        ("c", 1, None),
        ("d", 2, None),
        ("e", None, T2),
    ):
        session.add(
            models.Post(
                media_pk=media_pk,
                shortcode=media_pk,
                url=media_pk,
                event_id=event_id,
                last_scanned_at=scanned,
            )
        )
    session.commit()
    repo = EventRepository(session)
    assert repo.post_counts() == {1: 3, 2: 1}
    assert repo.last_scanned() == {1: T2}
    with _count_statements(session) as stmts:
        repo.post_counts()
        repo.last_scanned()
    assert len(stmts) == 2
    assert all("GROUP BY" in s for s in stmts)


# -- SQLite setup (S15) -----------------------------------------------------------


def _pragma(engine: Engine, name: str) -> Any:
    with engine.connect() as conn:
        return conn.exec_driver_sql(f"PRAGMA {name}").scalar()


def test_file_engine_uses_wal_and_busy_timeout(tmp_path: Path) -> None:
    engine = db.build_engine(f"sqlite:///{tmp_path / 'app.db'}")
    try:
        assert str(_pragma(engine, "journal_mode")).lower() == "wal"
        assert _pragma(engine, "busy_timeout") == 5000
        assert _pragma(engine, "synchronous") == 1  # NORMAL
    finally:
        engine.dispose()


def test_memory_engine_still_works() -> None:
    engine = db.build_engine("sqlite://")
    try:
        assert str(_pragma(engine, "journal_mode")).lower() == "memory"
        db.create_db_and_tables(engine)
        with Session(engine) as s:
            assert s.exec(select(models.User)).all() == []
    finally:
        engine.dispose()


_NEW_INDEXES = {
    "ix_campaigns_status",
    "ix_campaign_targets_campaign_id_status",
    "ix_users_profile_synced_at",
    "ix_posts_event_id",
}


def _index_names(engine: Engine) -> set[str]:
    with engine.connect() as conn:
        rows = conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type = 'index'")
        return {r[0] for r in rows}


def test_startup_adds_indexes_to_existing_db_without_data_loss(tmp_path: Path) -> None:
    engine = db.build_engine(f"sqlite:///{tmp_path / 'old.db'}")
    try:
        # An old DB: posts predates the event_id column (and so its index).
        with engine.begin() as conn:
            conn.exec_driver_sql(
                "CREATE TABLE posts (media_pk VARCHAR NOT NULL PRIMARY KEY, "
                "shortcode VARCHAR NOT NULL, url VARCHAR NOT NULL, caption VARCHAR NOT NULL, "
                "taken_at DATETIME, last_scanned_at DATETIME)"
            )
            conn.exec_driver_sql("INSERT INTO posts VALUES ('p1', 's1', 'u1', 'cap', NULL, NULL)")
        db.create_db_and_tables(engine)
        for name in _NEW_INDEXES:
            with engine.begin() as conn:
                conn.exec_driver_sql(f"DROP INDEX IF EXISTS {name}")
        assert not (_NEW_INDEXES & _index_names(engine))

        db.create_db_and_tables(engine)  # startup on the old DB
        db.create_db_and_tables(engine)  # and again: idempotent

        assert _index_names(engine) >= _NEW_INDEXES
        with Session(engine) as s:
            post = s.get(models.Post, "p1")
            assert post is not None and (post.shortcode, post.caption) == ("s1", "cap")
    finally:
        engine.dispose()


def test_startup_migrates_db_missing_column_and_index(tmp_path: Path) -> None:
    """S15: an older DB (missing a column and indexes) is upgraded in place, idempotently."""
    import sqlite3

    path = tmp_path / "older.db"
    eng = db.build_engine(f"sqlite:///{path}")
    SQLModel.metadata.create_all(eng)
    eng.dispose()
    con = sqlite3.connect(path)
    con.execute("DROP INDEX ix_users_profile_synced_at")
    con.execute("DROP INDEX ix_users_username")
    con.execute("ALTER TABLE users DROP COLUMN profile_synced_at")
    con.commit()
    con.close()

    eng = db.build_engine(f"sqlite:///{path}")
    db.create_db_and_tables(eng)
    db.create_db_and_tables(eng)  # second run must be a no-op
    with eng.connect() as conn:
        names = {
            r[0] for r in conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='index'")
        }
        cols = {r[1] for r in conn.exec_driver_sql("PRAGMA table_info(users)")}
    eng.dispose()
    assert {"ix_users_profile_synced_at", "ix_users_username"} <= names
    assert "profile_synced_at" in cols
