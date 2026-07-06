"""Plain result objects returned by use cases (API-agnostic)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.domain.entities import EngagementType
from app.domain.traffic_light import TrafficLight


@dataclass(frozen=True, slots=True)
class ScannedPost:
    media_pk: str
    shortcode: str
    url: str
    caption: str
    taken_at: datetime | None


@dataclass(frozen=True, slots=True)
class ScanResult:
    post: ScannedPost
    users_found: int
    new_users: int


@dataclass(frozen=True, slots=True)
class ScanBatchResult:
    results: list[ScanResult]
    total_users_found: int
    total_new_users: int
    skipped: int = 0  # posts skipped because scanned recently (cache)


@dataclass(frozen=True, slots=True)
class SyncResult:
    threads_synced: int
    users_touched: int
    incremental: bool = False  # only changed threads pulled (vs full inbox)


@dataclass(frozen=True, slots=True)
class EnrichResult:
    enriched: int  # profiles fetched (follower count / verified / bio)
    relations: int  # users whose follow-status was set
    relations_cached: bool = False  # relationships were fresh, fetch skipped


@dataclass(frozen=True, slots=True)
class UserEngagement:
    post_media_pk: str
    type: EngagementType
    comment_text: str | None
    post_url: str | None = None  # link to the post (opens the comment/like in context)


@dataclass(frozen=True, slots=True)
class UserView:
    pk: str
    username: str
    full_name: str
    profile_pic_url: str | None
    is_private: bool
    traffic_light: TrafficLight
    thread_id: str | None
    action_url: str
    last_message_at: datetime | None
    engagement_count: int = 0  # distinct posts engaged (fan-score, global)
    follows_us: bool | None = None
    we_follow: bool | None = None
    follower_count: int | None = None
    is_verified: bool = False
    is_business: bool = False
    biography: str | None = None
    event_engaged: int = 0  # posts of THIS fiesta this user engaged
    event_posts_total: int = 0  # posts in THIS fiesta
    last_engaged_at: datetime | None = None
    engagements: list[UserEngagement] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class StatusCounts:
    red: int
    yellow: int
    green: int
    total: int
