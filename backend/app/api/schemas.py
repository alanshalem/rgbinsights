"""API request/response models. These define the OpenAPI the TS client is generated from."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.domain.entities import EngagementType
from app.domain.traffic_light import TrafficLight

# -- requests -----------------------------------------------------------


class ScanPostRequest(BaseModel):
    url: str = Field(examples=["https://instagram.com/p/Cabc123/"])


class ScanPostsRequest(BaseModel):
    urls: list[str] | None = None
    date_from: datetime | None = Field(default=None, alias="from")
    date_to: datetime | None = Field(default=None, alias="to")

    model_config = {"populate_by_name": True}


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
    engagements: list[UserEngagementOut]


class PostOut(BaseModel):
    media_pk: str
    shortcode: str
    url: str
    caption: str
    taken_at: datetime | None
    last_scanned_at: datetime | None


class HealthOut(BaseModel):
    status: str
    using_fake_instagram: bool


class ErrorOut(BaseModel):
    code: str
    message: str
