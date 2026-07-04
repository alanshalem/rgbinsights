"""Repositories — the only place that reads/writes SQLModel rows.

Upserts are keyed by stable ids (user.pk, post.media_pk, thread_id) so
re-running a scan updates in place instead of duplicating.
"""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Session, col, select

from app.domain.entities import EngagementType, Friendship, IgUser, Post, ProfileInfo
from app.infrastructure.persistence import models


class UserRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert(self, user: IgUser, now: datetime) -> bool:
        """Upsert a user by pk. Returns True if newly inserted."""
        row = self.session.get(models.User, user.pk)
        if row is None:
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
            return True
        # username can change over time; keep the latest.
        row.username = user.username
        row.full_name = user.full_name
        row.profile_pic_url = user.profile_pic_url
        row.is_private = user.is_private
        row.last_seen_at = now
        self.session.add(row)
        return False

    def all_pks(self) -> list[str]:
        return list(self.session.exec(select(models.User.pk)))

    def set_friendships(self, rels: dict[str, Friendship]) -> None:
        for pk, fr in rels.items():
            row = self.session.get(models.User, pk)
            if row is not None:
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
        """Users (from the given pks) whose profile hasn't been fetched yet."""
        rows = []
        for pk in pks:
            row = self.session.get(models.User, pk)
            if row is not None and row.profile_synced_at is None:
                rows.append(row)
        return rows


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

    def upsert(
        self,
        user_pk: str,
        post_media_pk: str,
        type_: EngagementType,
        comment_text: str | None,
        created_at: datetime | None,
    ) -> bool:
        """Idempotent on (user_pk, post_media_pk, type). True if new."""
        existing = self.session.exec(
            select(models.Engagement).where(
                models.Engagement.user_pk == user_pk,
                models.Engagement.post_media_pk == post_media_pk,
                models.Engagement.type == type_.value,
            )
        ).first()
        if existing is not None:
            # Refresh comment text in case an edited comment was re-scanned.
            if type_ is EngagementType.COMMENT and comment_text is not None:
                existing.comment_text = comment_text
                self.session.add(existing)
            return False
        self.session.add(
            models.Engagement(
                user_pk=user_pk,
                post_media_pk=post_media_pk,
                type=type_.value,
                comment_text=comment_text,
                created_at=created_at,
            )
        )
        return True


class DmThreadRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert(
        self,
        thread_id: str,
        user_pk: str,
        has_outgoing: bool,
        has_incoming: bool,
        last_outgoing_at: datetime | None,
        last_incoming_at: datetime | None,
        last_message_at: datetime | None,
        synced_at: datetime,
    ) -> None:
        row = self.session.get(models.DmThread, thread_id)
        if row is None:
            row = models.DmThread(thread_id=thread_id, user_pk=user_pk, last_synced_at=synced_at)
        row.user_pk = user_pk
        row.has_outgoing = has_outgoing
        row.has_incoming = has_incoming
        row.last_outgoing_at = last_outgoing_at
        row.last_incoming_at = last_incoming_at
        row.last_message_at = last_message_at
        row.last_synced_at = synced_at
        self.session.add(row)

    def by_user_pk(self) -> dict[str, models.DmThread]:
        """Map user_pk -> thread. One thread per user in this app's scope."""
        rows = self.session.exec(select(models.DmThread))
        return {row.user_pk: row for row in rows}


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
        counts: dict[int, int] = {}
        for row in self.session.exec(select(models.Post.event_id)):
            if row is not None:
                counts[row] = counts.get(row, 0) + 1
        return counts
