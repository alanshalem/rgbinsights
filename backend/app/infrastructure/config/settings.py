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

    # Which data source to use: "fake" | "web" | "playwright" | "instagrapi".
    #   web        -> browser web API via IG_SESSIONID (only /users/* works)
    #   playwright -> real logged-in headless browser (recommended for real use)
    #   instagrapi -> mobile private API via user/password (needs a mobile login)
    # Empty falls back to use_fake_instagram for backward compat.
    ig_source: str = ""

    # Playwright source: on-disk browser profile (persists the login) + headless.
    ig_browser_dir: str = ".pw-profile"
    ig_browser_headless: bool = True

    def resolved_source(self) -> str:
        src = self.ig_source.strip().lower()
        if src:
            return src
        return "fake" if self.use_fake_instagram else "instagrapi"

    # How many recent posts to pull when scanning by date range.
    recent_posts_limit: int = 50


@lru_cache
def get_settings() -> Settings:
    return Settings()
