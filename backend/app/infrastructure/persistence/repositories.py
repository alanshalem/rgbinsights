"""Repositories — the only place that reads/writes SQLModel rows.

Upserts are keyed by stable ids (user.pk, post.media_pk, thread_id) so
re-running a scan updates in place instead of duplicating. Batch upserts load
the existing rows with one chunked `SELECT ... IN` and let the session flush
the inserts/updates in bulk, instead of one round-trip per row. The caller
commits once per batch.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, insert
from sqlmodel import Session, col, select

from app.domain.entities import EngagementType, Friendship, IgUser, Post, ProfileInfo
from app.infrastructure.persistence import models

# Max bound parameters per IN (...) chunk: well under SQLite's variable limit.
IN_CHUNK = 900


def chunked(items: list[Any], size: int = IN_CHUNK) -> Iterator[list[Any]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


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


class UserRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert_many(self, users: Iterable[IgUser], now: datetime) -> set[str]:
        """Upsert users by pk; returns the pks that were newly inserted.

        A pk seen twice keeps its first position but the last data (same as
        upserting one by one). first_seen_at is only set on insert.
        """
        latest: dict[str, IgUser] = {}
        for user in users:
            latest[user.pk] = user
        existing: dict[str, models.User] = {}
        for chunk in chunked(list(latest)):
            for row in self.session.exec(select(models.User).where(col(models.User.pk).in_(chunk))):
                existing[row.pk] = row
        inserted: set[str] = set()
        for pk, user in latest.items():
            found = existing.get(pk)
            if found is None:
                self.session.add(
                    models.User(
                        pk=user.pk,
                        username=user.username,
                        full_name=user.full_name,
                        profile_pic_url=user.profile_pic_url,
                        is_private=user.is_private,
                        first_seen_at=now,
                        last_seen_at=now,
                    )
                )
                inserted.add(pk)
                continue
            # username can change over time; keep the latest.
            found.username = user.username
            found.full_name = user.full_name
            found.profile_pic_url = user.profile_pic_url
            found.is_private = user.is_private
            found.last_seen_at = now
            self.session.add(found)
        return inserted

    def all_pks(self) -> list[str]:
        return list(self.session.exec(select(models.User.pk)))

    def set_friendships(self, rels: dict[str, Friendship]) -> None:
        if not rels:
            return
        rows = self.session.exec(select(models.User).where(col(models.User.pk).in_(list(rels))))
        for row in rows:
            fr = rels[row.pk]
            row.follows_us = fr.followed_by
            row.we_follow = fr.following
            self.session.add(row)

    def set_profile(self, pk: str, profile: ProfileInfo, now: datetime) -> None:
        row = self.session.get(models.User, pk)
        if row is None:
            return
        row.follower_count = profile.follower_count
        row.is_verified = profile.is_verified
        row.is_business = profile.is_business
        row.biography = profile.biography
        if profile.profile_pic_url:
            row.profile_pic_url = profile.profile_pic_url
        row.profile_synced_at = now
        self.session.add(row)

    def unenriched(self, pks: list[str]) -> list[models.User]:
        """Users (from the given pks) whose profile hasn't been fetched yet.

        One query instead of N gets; input order is preserved (the enrich loop
        may be capped by `limit`, so which users come first must stay stable).
        """
        if not pks:
            return []
        found = {
            u.pk: u
            for u in self.session.exec(
                select(models.User).where(
                    col(models.User.pk).in_(pks),
                    col(models.User.profile_synced_at).is_(None),
                )
            )
        }
        return [found[pk] for pk in pks if pk in found]


class PostRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert(self, post: Post, scanned_at: datetime, event_id: int | None = None) -> models.Post:
        row = self.session.get(models.Post, post.media_pk)
        if row is None:
            row = models.Post(media_pk=post.media_pk, shortcode=post.shortcode, url=post.url)
        row.shortcode = post.shortcode
        row.url = post.url
        row.caption = post.caption
        row.taken_at = post.taken_at
        row.last_scanned_at = scanned_at
        # Only (re)assign the fiesta when one is given; a plain re-scan keeps it.
        if event_id is not None:
            row.event_id = event_id
        self.session.add(row)
        return row

    def list_all(self, event_id: int | None = None) -> list[models.Post]:
        stmt = select(models.Post)
        if event_id is not None:
            stmt = stmt.where(models.Post.event_id == event_id)
        return list(self.session.exec(stmt.order_by(col(models.Post.taken_at))))

    def get(self, media_pk: str) -> models.Post | None:
        return self.session.get(models.Post, media_pk)


class EngagementRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert_many(self, post_media_pk: str, items: Iterable[EngagementIn]) -> None:
        """Idempotent on (user_pk, post_media_pk, type), in input order.

        One SELECT loads the post's existing rows; new rows go out in one
        executemany INSERT (ids keep input order). A repeated key only
        refreshes the comment text (edited comment); created_at keeps the
        first value seen.
        """
        existing: dict[tuple[str, str], models.Engagement] = {
            (row.user_pk, row.type): row
            for row in self.session.exec(
                select(models.Engagement).where(models.Engagement.post_media_pk == post_media_pk)
            )
        }
        new: dict[tuple[str, str], dict[str, Any]] = {}
        for item in items:
            key = (item.user_pk, item.type.value)
            refresh = item.type is EngagementType.COMMENT and item.comment_text is not None
            if (found := existing.get(key)) is not None:
                if refresh:
                    found.comment_text = item.comment_text
                    self.session.add(found)
            elif (pending := new.get(key)) is not None:
                if refresh:
                    pending["comment_text"] = item.comment_text
            else:
                new[key] = {
                    "user_pk": item.user_pk,
                    "post_media_pk": post_media_pk,
                    "type": item.type.value,
                    "comment_text": item.comment_text,
                    "created_at": item.created_at,
                }
        if new:
            self.session.execute(insert(models.Engagement), list(new.values()))


class DmThreadRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert_many(self, threads: Iterable[ThreadIn], synced_at: datetime) -> None:
        """Upsert threads by thread_id, overwriting every field (last one wins)."""
        latest: dict[str, ThreadIn] = {}
        for thread in threads:
            latest[thread.thread_id] = thread
        existing: dict[str, models.DmThread] = {}
        for chunk in chunked(list(latest)):
            for row in self.session.exec(
                select(models.DmThread).where(col(models.DmThread.thread_id).in_(chunk))
            ):
                existing[row.thread_id] = row
        for thread_id, t in latest.items():
            row = existing.get(thread_id) or models.DmThread(
                thread_id=thread_id, user_pk=t.user_pk, last_synced_at=synced_at
            )
            row.user_pk = t.user_pk
            row.has_outgoing = t.has_outgoing
            row.has_incoming = t.has_incoming
            row.last_outgoing_at = t.last_outgoing_at
            row.last_incoming_at = t.last_incoming_at
            row.last_message_at = t.last_message_at
            row.last_synced_at = synced_at
            self.session.add(row)


class EventRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, event: models.Event) -> models.Event:
        self.session.add(event)
        self.session.commit()
        self.session.refresh(event)
        return event

    def get(self, event_id: int) -> models.Event | None:
        return self.session.get(models.Event, event_id)

    def list_all(self) -> list[models.Event]:
        return list(self.session.exec(select(models.Event).order_by(col(models.Event.event_date))))

    def post_counts(self) -> dict[int, int]:
        """event_id -> number of posts assigned."""
        event_id = col(models.Post.event_id)
        stmt = select(event_id, func.count()).where(event_id.is_not(None)).group_by(event_id)
        return {eid: count for eid, count in self.session.exec(stmt) if eid is not None}

    def last_scanned(self) -> dict[int, datetime]:
        """event_id -> most recent post scan (for the 'posts hace Xh' hint)."""
        event_id = col(models.Post.event_id)
        scanned = col(models.Post.last_scanned_at)
        stmt = (
            select(event_id, func.max(scanned))
            .where(event_id.is_not(None), scanned.is_not(None))
            .group_by(event_id)
        )
        return {
            eid: latest
            for eid, latest in self.session.exec(stmt)
            if eid is not None and latest is not None
        }


class AppStateRepository:
    """Persisted singletons (timestamps) for cache/TTL decisions."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_dt(self, key: str) -> datetime | None:
        row = self.session.get(models.AppState, key)
        if row is None:
            return None
        try:
            return datetime.fromisoformat(row.value)
        except ValueError:
            return None

    def set_dt(self, key: str, when: datetime) -> None:
        row = self.session.get(models.AppState, key)
        if row is None:
            row = models.AppState(key=key, value=when.isoformat())
        else:
            row.value = when.isoformat()
        self.session.add(row)
