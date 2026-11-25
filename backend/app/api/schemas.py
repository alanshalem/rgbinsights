"""API request/response models. These define the OpenAPI the TS client is generated from."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.domain.entities import EngagementType
from app.domain.traffic_light import TrafficLight

# -- requests -----------------------------------------------------------


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
    last_scanned_at: datetime | None = None


# -- responses ----------------------------------------------------------


class UserEngagementOut(BaseModel):
    post_media_pk: str
    type: EngagementType
    comment_text: str | None
    post_url: str | None


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
    """A background job (scan / rescan / sync / refresh / enrich): its progress
    while it runs, then `result` (the summary) or `error` (Spanish, as shown)."""

    id: str
    kind: str  # scan | rescan | sync | refresh | enrich
    label: str
    status: str  # running | done | error
    current: int
    total: int
    message: str
    result: dict[str, Any]
    warning: str | None = None  # Spanish: shown on its own line (the job is still done)
    error: str | None
    error_code: str | None = None  # e.g. challenge_required -> the reconnect banner
    started_at: datetime
    finished_at: datetime | None


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


class StatusOut(BaseModel):
    """Freshness of the shared (global) data, for the 'hace Xh' hints."""

    relationships_synced_at: datetime | None
    dms_synced_at: datetime | None


class IgStatusOut(BaseModel):
    """Instagram session health, for the connection chip + reconnect banner."""

    state: str  # connected | disconnected
    pk: str | None
    last_ok_at: datetime | None
    demo: bool  # the dev/test fake source (RGB_DEV_FAKE_INSTAGRAM), never for users
    source: str  # fake | instagrapi — drives the reconnect UI
    has_saved_session: bool  # session.json exists ("Volver a conectar" can re-check it)
    # No Instagram request before this (login breaker or throttle cooldown open).
    cooldown_until: datetime | None = None
    last_error: str | None = None  # the most recent Instagram failure, if any


class IgSessionIdIn(BaseModel):
    sessionid: str


class EstimateOut(BaseModel):
    per_day: int
    days: int
    avg_delay_seconds: float
    window_hours: int
    minutes_per_day: float


class MessageSample(BaseModel):
    username: str
    message: str


class PresetOut(BaseModel):
    name: str
    delay_min: int
    delay_max: int
    daily_cap: int
    hour_start: int
    hour_end: int


class CampaignPreviewOut(BaseModel):
    targets_count: int
    follower_targets: int  # how many targets already follow us (safest to DM)
    estimate: EstimateOut
    samples: list[MessageSample]
    optimal: PresetOut  # auto-computed sweet-spot rate (~2-3 days, safest pace)


class ResetIn(BaseModel):
    confirm: str


class ResetOut(BaseModel):
    deleted: dict[str, int]


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


# -- in-app configuration (S25) ---------------------------------------------


class ConfigEntryOut(BaseModel):
    """One setting of the "Configuración" screen. Numbers may only move inside
    [min, max] (the safer side of the factory value, S0)."""

    key: str
    kind: Literal["int", "float"]
    value: int | float
    default: int | float  # an older install's environment value, else the factory one
    min: float | None
    max: float | None
    unit: str
    group: str
    label: str
    help: str
    overridden: bool  # changed in the app (else it follows `default`)
    at_most: str | None = None  # the key this one may not exceed (a min/max pair)
    # What an older .env asked for, when it had to be pulled inside the bounds.
    clamped_from: float | None = None


class ConfigOut(BaseModel):
    entries: list[ConfigEntryOut]


class ConfigUpdateIn(BaseModel):
    """A partial update: only the settings to change, key -> new value."""

    values: dict[str, Any]


class ConfigResetIn(BaseModel):
    key: str | None = None  # null: every setting back to its default
