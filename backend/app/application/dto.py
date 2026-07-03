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


@dataclass(frozen=True, slots=True)
class SyncResult:
    threads_synced: int
    users_touched: int


@dataclass(frozen=True, slots=True)
class UserEngagement:
    post_media_pk: str
    type: EngagementType
    comment_text: str | None


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
    engagement_count: int = 0  # distinct posts engaged (fan-score)
    engagements: list[UserEngagement] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class StatusCounts:
    red: int
    yellow: int
    green: int
    total: int
