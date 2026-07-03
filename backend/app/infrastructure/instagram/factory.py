"""Selects the InstagramSource implementation from settings (IG_SOURCE)."""

from __future__ import annotations

from app.infrastructure.config.settings import Settings
from app.infrastructure.instagram.base import InstagramSource


def build_source(settings: Settings) -> InstagramSource:
    source = settings.resolved_source()
    if source == "fake":
        from app.infrastructure.instagram.fake_source import FakeInstagramSource

        return FakeInstagramSource()
    if source == "web":
        from app.infrastructure.instagram.web_source import WebInstagramSource

        return WebInstagramSource(settings)
    if source == "playwright":
        from app.infrastructure.instagram.playwright_source import PlaywrightInstagramSource

        return PlaywrightInstagramSource(settings)
    from app.infrastructure.instagram.instagrapi_source import InstagrapiInstagramSource

    return InstagrapiInstagramSource(settings)
