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

    # Anti-block hygiene (all optional). A stable proxy + consistent
    # country/locale make the account look far less suspicious to Instagram.
    ig_proxy: str = ""  # e.g. http://user:pass@host:port
    ig_country: str = ""  # e.g. AR
    ig_locale: str = ""  # e.g. es_AR

    database_url: str = "sqlite:///./rgb.db"

    # Rate limiting / good behaviour.
    scan_min_delay_seconds: float = 1.0
    scan_max_delay_seconds: float = 3.0
    scan_max_requests: int = 200

    # When true (default), the app uses FakeInstagramSource and never touches
    # Instagram. Set to false once credentials are filled in .env.
    use_fake_instagram: bool = True

    # How many recent posts to pull when scanning by date range.
    recent_posts_limit: int = 50


@lru_cache
def get_settings() -> Settings:
    return Settings()
