"""API request/response models. These define the OpenAPI the TS client is generated from."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.domain.entities import EngagementType
from app.domain.traffic_light import TrafficLight

# -- requests -----------------------------------------------------------


class ScanPostRequest(BaseModel):
    url: str = Field(examples=["https://instagram.com/p/Cabc123/"])
    event_id: int | None = None


class ScanPostsRequest(BaseModel):
    urls: list[str] | None = None
    date_from: datetime | None = Field(default=None, alias="from")
    date_to: datetime | None = Field(default=None, alias="to")
    event_id: int | None = None

    model_config = {"populate_by_name": True}


class EventCreate(BaseModel):
    name: str
    promo_start: datetime
    event_date: datetime
    notes: str | None = None


class EventUpdate(BaseModel):
    name: str | None = None
    promo_start: datetime | None = None
    event_date: datetime | None = None
    notes: str | None = None


class EventOut(BaseModel):
    id: int
    name: str
    promo_start: datetime
    event_date: datetime
    notes: str | None
    posts_count: int


# -- responses ----------------------------------------------------------


class ScannedPostOut(BaseModel):
    media_pk: str
    shortcode: str
    url: str
    caption: str
    taken_at: datetime | None


class ScanResultOut(BaseModel):
    post: ScannedPostOut
    users_found: int
    new_users: int


class ScanBatchResultOut(BaseModel):
    results: list[ScanResultOut]
    total_users_found: int
    total_new_users: int


class SyncResultOut(BaseModel):
    threads_synced: int
    users_touched: int


class EventRefreshOut(BaseModel):
    scan: ScanBatchResultOut
    sync: SyncResultOut


class UserEngagementOut(BaseModel):
    post_media_pk: str
    type: EngagementType
    comment_text: str | None


class UserOut(BaseModel):
    pk: str
    username: str
    full_name: str
    profile_pic_url: str | None
    is_private: bool
    traffic_light: TrafficLight
    thread_id: str | None
    action_url: str
    last_message_at: datetime | None
    engagement_count: int
    follows_us: bool | None
    we_follow: bool | None
    follower_count: int | None
    is_verified: bool
    is_business: bool
    biography: str | None
    event_engaged: int
    event_posts_total: int
    last_engaged_at: datetime | None
    engagements: list[UserEngagementOut]


class StatusCountsOut(BaseModel):
    red: int
    yellow: int
    green: int
    total: int


class PostOut(BaseModel):
    media_pk: str
    shortcode: str
    url: str
    caption: str
    taken_at: datetime | None
    last_scanned_at: datetime | None
    event_id: int | None


class HealthOut(BaseModel):
    status: str
    using_fake_instagram: bool


class ErrorOut(BaseModel):
    code: str
    message: str


class TaskOut(BaseModel):
    id: str
    kind: str
    label: str
    status: str  # running | done | error
    current: int
    total: int
    message: str
    result: dict[str, Any]
    error: str | None


class ActivityOut(BaseModel):
    id: int
    kind: str
    status: str
    message: str
    created_at: datetime


# -- campaigns (bulk DM) ------------------------------------------------


class SendParamsIn(BaseModel):
    delay_min: int = Field(ge=10, le=3600)
    delay_max: int = Field(ge=10, le=3600)
    daily_cap: int = Field(ge=1, le=200)
    hour_start: int = Field(ge=0, le=23)
    hour_end: int = Field(ge=1, le=24)


class CampaignCreate(SendParamsIn):
    templates: list[str]
    only_followers: bool = False  # DM only users who follow us (safest)
    followers_first: bool = False  # order followers/mutuals first


class EnrichResultOut(BaseModel):
    enriched: int
    relations: int


class EstimateOut(BaseModel):
    per_day: int
    days: int
    avg_delay_seconds: float


class MessageSample(BaseModel):
    username: str
    message: str


class CampaignPreviewOut(BaseModel):
    targets_count: int
    estimate: EstimateOut
    samples: list[MessageSample]


class PresetOut(BaseModel):
    name: str
    delay_min: int
    delay_max: int
    daily_cap: int
    hour_start: int
    hour_end: int


class CampaignOut(BaseModel):
    id: int
    event_id: int
    status: str  # running | paused | blocked | done
    total: int
    sent: int
    pending: int
    failed: int
    sent_today: int
    daily_cap: int
    delay_min: int
    delay_max: int
    hour_start: int
    hour_end: int
    last_sent_at: datetime | None
    error: str | None
