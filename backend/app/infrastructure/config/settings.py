"""App settings from the environment (`.env`) via pydantic-settings.

Since S25 the environment holds only what can't live in the app: the optional
proxy. The Instagram session comes from a sessionid pasted in the app (L24:
no username/password, 2FA seed or sessionid in the environment any more; such
older entries are ignored). Every behaviour setting (pacing, budgets, caps,
caches) is edited in the "Configuración" screen and stored in the DB (see
app.application.runtime_config); the fields below for them are only its
defaults, read from an older .env so existing installs keep their values
(always pulled inside the safety bounds of app.domain.config).
"""

from __future__ import annotations

import dataclasses
from datetime import timedelta, timezone
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.domain.config import FACTORY, RuntimeConfig

# Anti-block hygiene: the account looks like one stable phone in Argentina
# (country, locale and the timezone we report to Instagram). Fixed on purpose.
IG_COUNTRY = "AR"
IG_LOCALE = "es_AR"
IG_TIMEZONE_OFFSET = -10800  # seconds from UTC (AR = UTC-3, no DST)

# The Instagram source: the real account (what the app always uses) or the
# fake one, a dev/test tool only (L27: invented data, no user setting).
SOURCE_REAL = "instagrapi"
SOURCE_FAKE = "fake"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", populate_by_name=True
    )

    # A stable proxy makes the account look far less suspicious to Instagram.
    ig_proxy: str = ""  # e.g. http://user:pass@host:port

    def local_tz(self) -> timezone:
        """The account's local time (campaign hours, daily caps, budget windows).

        A fixed offset on purpose: it is the same timezone we report to Instagram,
        Argentina has no DST, and Windows ships no tz database for zoneinfo.
        """
        return timezone(timedelta(seconds=IG_TIMEZONE_OFFSET))

    # Development/test overrides (not documented for users).
    database_url: str = "sqlite:///./rgb.db"
    # The saved Instagram session (written by the in-app sessionid paste).
    ig_session_file: str = "session.json"
    # Breaker/cooldown/budget state (a small JSON file, survives restarts).
    ig_guard_file: str = "ig_guard.json"

    # -- defaults of the in-app configuration (legacy .env values) -------------
    # Meaning, bounds and labels: app.domain.config.

    scan_min_delay_seconds: float = FACTORY.scan_min_delay_seconds
    scan_max_delay_seconds: float = FACTORY.scan_max_delay_seconds
    ig_rest_every_requests: int = FACTORY.ig_rest_every_requests
    ig_rest_min_seconds: float = FACTORY.ig_rest_min_seconds
    ig_rest_max_seconds: float = FACTORY.ig_rest_max_seconds
    ig_max_requests_per_hour: int = FACTORY.ig_max_requests_per_hour
    ig_max_requests_per_day: int = FACTORY.ig_max_requests_per_day
    ig_throttle_cooldown_minutes: float = FACTORY.ig_throttle_cooldown_minutes
    ig_lock_wait_seconds: float = FACTORY.ig_lock_wait_seconds
    recent_posts_limit: int = FACTORY.recent_posts_limit
    dm_threads_limit: int = FACTORY.dm_threads_limit
    scan_comments_limit: int = FACTORY.scan_comments_limit
    relationship_fetch_max: int = FACTORY.relationship_fetch_max
    enrich_profiles_per_run: int = FACTORY.enrich_profiles_per_run
    enrich_profiles_per_day: int = FACTORY.enrich_profiles_per_day
    relationship_cache_hours: float = FACTORY.relationship_cache_hours
    rescan_skip_hours: float = FACTORY.rescan_skip_hours
    relationship_full_refresh_days: float = FACTORY.relationship_full_refresh_days

    # The Instagram source is always the real account, which makes no request
    # until a sessionid is pasted (L25). Development/tests only (L27/L28): the
    # fake source (invented data, never touches Instagram), switched on by
    # RGB_DEV_FAKE_INSTAGRAM=1 — a name no user .env has. The old IG_SOURCE and
    # USE_FAKE_INSTAGRAM are not read at all: an old .env with them must never
    # leave the app stuck on invented data.
    dev_fake_instagram: bool = Field(default=False, validation_alias="rgb_dev_fake_instagram")

    @property
    def ig_source(self) -> str:
        """The Instagram source in use: "instagrapi", or "fake" for dev/tests."""
        return SOURCE_FAKE if self.dev_fake_instagram else SOURCE_REAL

    @property
    def is_fake(self) -> bool:
        """The dev/test fake source (RGB_DEV_FAKE_INSTAGRAM=1): no Instagram at all."""
        return self.dev_fake_instagram

    def runtime_defaults(self) -> RuntimeConfig:
        """These settings' values for the in-app configuration, as they are (the
        configuration service pulls them inside the safety bounds)."""
        names = (f.name for f in dataclasses.fields(RuntimeConfig))
        return RuntimeConfig(**{name: getattr(self, name) for name in names})

    def with_runtime(self, config: RuntimeConfig) -> Settings:
        """A copy carrying the effective in-app configuration."""
        return self.model_copy(update=dataclasses.asdict(config))


@lru_cache
def get_settings() -> Settings:
    return Settings()
