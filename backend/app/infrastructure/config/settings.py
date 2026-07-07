"""App settings from .env via pydantic-settings."""

from __future__ import annotations

from functools import lru_cache

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

    database_url: str = "sqlite:///./rgb.db"

    # Rate limiting / good behaviour.
    scan_min_delay_seconds: float = 1.0
    scan_max_delay_seconds: float = 3.0
    # Per-operation request cap (anti-runaway). Reset before each op; high enough
    # that enriching a few hundred profiles in one run doesn't trip it.
    scan_max_requests: int = 1500

    # When true (default), the app uses FakeInstagramSource and never touches
    # Instagram. Set to false once credentials are filled in .env.
    use_fake_instagram: bool = True

    # Which data source to use: "fake" | "instagrapi".
    #   instagrapi -> mobile private API, seeded by IG_SESSIONID / user+password.
    # Empty falls back to use_fake_instagram for backward compat.
    ig_source: str = ""

    def resolved_source(self) -> str:
        """Only 'fake' or 'instagrapi' remain; anything real maps to instagrapi."""
        if self.ig_source.strip().lower() == "fake":
            return "fake"
        if not self.ig_source.strip() and self.use_fake_instagram:
            return "fake"
        return "instagrapi"

    # How many recent posts to pull when scanning by date range.
    recent_posts_limit: int = 50

    # Cap comments read per post: without a cap instagrapi pages EVERY comment on
    # a viral post (hundreds of private-API requests = ban risk). 200 recent
    # comments is plenty to catch engaged users.
    scan_comments_limit: int = 200

    # Optional cap on followers/following fetched to compute "te sigue"
    # membership. 0 = all (correct but heaviest). Set >0 on accounts with a huge
    # graph to trade completeness for far fewer requests.
    relationship_fetch_max: int = 0

    # Caching to spare Instagram requests (and lower ban risk). Each is a TTL:
    # within it the app reuses stored data instead of re-fetching. "force" in the
    # UI bypasses them. See use_cases + the caching docs in Ayuda.
    relationship_cache_hours: float = 12.0  # skip re-reading followers/following
    rescan_skip_hours: float = 6.0  # skip re-scanning a post scanned this recently
    dm_incremental: bool = True  # only pull DM threads changed since last sync


@lru_cache
def get_settings() -> Settings:
    return Settings()
