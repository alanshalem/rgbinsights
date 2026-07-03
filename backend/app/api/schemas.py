"""API request/response models. These define the OpenAPI the TS client is generated from."""

from __future__ import annotations

from datetime import datetime

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
