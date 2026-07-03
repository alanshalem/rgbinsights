"""SQLModel persistence rows (the SQLite schema).

Kept separate from domain entities on purpose: the domain stays free of ORM
concerns, and these rows can evolve with the DB without touching the rules.
Identity for users is `pk` (stable IG numeric id), never username.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


class User(SQLModel, table=True):
    __tablename__ = "users"

    pk: str = Field(primary_key=True)
    username: str = Field(index=True)
    full_name: str = ""
    profile_pic_url: str | None = None
    is_private: bool = False
    first_seen_at: datetime
    last_seen_at: datetime


class Event(SQLModel, table=True):
    """A party (fiesta): groups posts and defines the semáforo cutoff."""

    __tablename__ = "events"

    id: int | None = Field(default=None, primary_key=True)
    name: str
    promo_start: datetime  # start of the campaign -> semáforo cutoff date
    event_date: datetime  # when the party happens/happened (metadata/status)
    notes: str | None = None
    created_at: datetime


class Post(SQLModel, table=True):
    __tablename__ = "posts"

    media_pk: str = Field(primary_key=True)
    shortcode: str = Field(index=True)
    url: str
    caption: str = ""
    taken_at: datetime | None = None
    last_scanned_at: datetime | None = None
    event_id: int | None = Field(default=None, foreign_key="events.id", index=True)


class Engagement(SQLModel, table=True):
    __tablename__ = "engagements"
    # Idempotent re-scans: one row per (user, post, type).
    __table_args__ = (
        UniqueConstraint("user_pk", "post_media_pk", "type", name="uq_engagement_user_post_type"),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_pk: str = Field(foreign_key="users.pk", index=True)
    post_media_pk: str = Field(foreign_key="posts.media_pk", index=True)
    type: str  # "comment" | "like"
    comment_text: str | None = None
    created_at: datetime | None = None


class DmThread(SQLModel, table=True):
    __tablename__ = "dm_threads"

    thread_id: str = Field(primary_key=True)
    user_pk: str = Field(foreign_key="users.pk", index=True)
    has_outgoing: bool = False
    has_incoming: bool = False
    # Timestamps of the last message in each direction, for the per-fiesta
    # date cutoff (a reply before the campaign started doesn't count).
    last_outgoing_at: datetime | None = None
    last_incoming_at: datetime | None = None
    last_message_at: datetime | None = None
    last_synced_at: datetime
