"""App settings from .env via pydantic-settings."""

from __future__ import annotations

from datetime import timedelta, timezone
from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Instagram credentials (only needed for the real adapter).
    ig_username: str = ""
    ig_password: str = ""
    ig_2fa_secret: str = ""  # optional TOTP seed
    ig_session_file: str = "session.json"

    # Preferred auth: reuse the `sessionid` cookie from a browser where you are
    # already logged in. Skips the API login flow entirely, so it dodges the
    # login checkpoint that user/password triggers. If set, it takes priority.
    ig_sessionid: str = ""

    # Anti-block hygiene. A stable proxy + consistent country/locale/timezone
    # make the account look far less suspicious to Instagram. Defaults target
    # Argentina (matching a local residential IP); override for another region.
    ig_proxy: str = ""  # e.g. http://user:pass@host:port
    ig_country: str = "AR"
    ig_locale: str = "es_AR"
    ig_timezone_offset: int = -10800  # seconds from UTC (AR = UTC-3)

    def local_tz(self) -> timezone:
        """The account's local time (campaign hours, daily caps, budget windows).

        A fixed offset on purpose: it is the same timezone we report to Instagram,
        Argentina has no DST, and Windows ships no tz database for zoneinfo.
        """
        return timezone(timedelta(seconds=self.ig_timezone_offset))

    database_url: str = "sqlite:///./rgb.db"

    # Human pacing before EVERY Instagram HTTP request (pages included). Each gap
    # is jittered between these bounds (never faster on average than their
    # midpoint), with an occasional longer "distraction" pause on top.
    scan_min_delay_seconds: float = 2.0
    scan_max_delay_seconds: float = 6.0
    # A long rest every N requests, like a person putting the phone down.
    ig_rest_every_requests: int = 25
    ig_rest_min_seconds: float = 45.0
    ig_rest_max_seconds: float = 150.0

    # Real request budget: every HTTP request to Instagram counts (each page of
    # followers/comments too). Windows are Argentina local hours/days; reaching a
    # cap stops all Instagram work until the window rolls over.
    ig_max_requests_per_hour: int = 200
    ig_max_requests_per_day: int = 1500
    # When Instagram answers 429 / "please wait" / feedback_required, every
    # Instagram request stops for this long (survives restarts).
    ig_throttle_cooldown_minutes: float = 60.0
    # Only one Instagram operation runs at a time; others wait this long at most.
    ig_lock_wait_seconds: float = 600.0
    # Breaker/cooldown/budget state (a small JSON file, survives restarts).
    ig_guard_file: str = "ig_guard.json"

    # The one data-source setting: "fake" (default: sample data, never touches
    # Instagram) or "instagrapi" (your real account, via the mobile private API,
    # seeded by IG_SESSIONID / user+password). Any other non-empty value (from an
    # older version) also means the real account.
    ig_source: str = ""
    # Legacy switch, read only so older .env files keep working: when IG_SOURCE
    # is empty, USE_FAKE_INSTAGRAM=false selects the real account. Never read it
    # in code — use `ig_source` (always "fake" or "instagrapi" after loading).
    use_fake_instagram: bool | None = None

    @model_validator(mode="after")
    def _resolve_source(self) -> Settings:
        raw = self.ig_source.strip().lower()
        if raw == "fake" or (not raw and self.use_fake_instagram is not False):
            self.ig_source = "fake"
        else:
            self.ig_source = "instagrapi"
        return self

    @property
    def is_fake(self) -> bool:
        """Demo mode: FakeInstagramSource, no Instagram at all."""
        return self.ig_source == "fake"

    @property
    def has_password_login(self) -> bool:
        """IG_USERNAME and IG_PASSWORD are both set (enables login/relogin)."""
        return bool(self.ig_username.strip() and self.ig_password.strip())

    # How many recent posts to pull when scanning by date range.
    recent_posts_limit: int = 50

    # DM threads read by a full (first or forced) DM sync. Later syncs page the
    # inbox newest-first only until the previous sync. 60 = 3 inbox pages, the
    # same requests the old fixed 50-thread read made.
    dm_threads_limit: int = 60

    # Cap comments read per post: without a cap instagrapi pages EVERY comment on
    # a viral post (hundreds of private-API requests = ban risk). 200 recent
    # comments is plenty to catch engaged users.
    scan_comments_limit: int = 200

    # Optional cap on followers/following fetched to compute "te sigue"
    # membership. 0 = all (correct but heaviest). Set >0 on accounts with a huge
    # graph to trade completeness for far fewer requests.
    relationship_fetch_max: int = 0
    # Between full reads, followers/following are read newest-first only until a
    # page of people we already know (only adds). A full read every N days also
    # catches unfollows.
    relationship_full_refresh_days: float = 7.0

    # "Relación + perfiles": profile reads per run and per Argentina-local day.
    # Progress is saved in batches, so the next run continues with the rest.
    enrich_profiles_per_run: int = 60
    enrich_profiles_per_day: int = 150

    # Caching to spare Instagram requests (and lower ban risk). Each is a TTL:
    # within it the app reuses stored data instead of re-fetching. "force" in the
    # UI bypasses them. See use_cases + the caching docs in Ayuda.
    relationship_cache_hours: float = 12.0  # skip re-reading followers/following
    rescan_skip_hours: float = 6.0  # skip re-scanning a post scanned this recently
    dm_incremental: bool = True  # only pull DM threads changed since last sync


@lru_cache
def get_settings() -> Settings:
    return Settings()
