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
    # Follow relationship (from show_many, filled on sync).
    follows_us: bool | None = None
    we_follow: bool | None = None
    # Richer profile (from get_profile, filled by the enrich step).
    follower_count: int | None = None
    is_verified: bool = False
    is_business: bool = False
    biography: str | None = None
    profile_synced_at: datetime | None = None


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


class Campaign(SQLModel, table=True):
    """A throttled bulk-DM run over a fiesta's red users."""

    __tablename__ = "campaigns"

    id: int | None = Field(default=None, primary_key=True)
    event_id: int = Field(foreign_key="events.id", index=True)
    status: str = "running"  # running | paused | blocked | done
    templates: str  # JSON list of message variants
    delay_min: int
    delay_max: int
    daily_cap: int
    hour_start: int
    hour_end: int
    sent_today: int = 0
    sent_today_date: str = ""  # ISO date the counter belongs to
    last_sent_at: datetime | None = None
    error: str | None = None  # why it got blocked, if any
    created_at: datetime


class ActivityLog(SQLModel, table=True):
    """One row per finished operation (scan/sync/enrich/campaign) — the history
    shown in the Actividad view, so you can see what ran without the terminal."""

    __tablename__ = "activity_log"

    id: int | None = Field(default=None, primary_key=True)
    kind: str
    status: str  # done | error
    message: str
    created_at: datetime


class AppState(SQLModel, table=True):
    """Tiny key→value store for singletons (e.g. last-followers-sync timestamp),
    so cache/TTL decisions survive restarts without a dedicated table each."""

    __tablename__ = "app_state"

    key: str = Field(primary_key=True)
    value: str


class CampaignTarget(SQLModel, table=True):
    __tablename__ = "campaign_targets"

    id: int | None = Field(default=None, primary_key=True)
    campaign_id: int = Field(foreign_key="campaigns.id", index=True)
    user_pk: str = Field(foreign_key="users.pk", index=True)
    username: str
    status: str = "pending"  # pending | sent | failed
    message: str | None = None
    sent_at: datetime | None = None
    error: str | None = None
