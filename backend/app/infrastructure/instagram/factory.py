"""Selects the InstagramSource implementation from settings (IG_SOURCE)."""

from __future__ import annotations

from app.infrastructure.config.settings import Settings
from app.infrastructure.instagram.base import InstagramSource


def build_source(settings: Settings) -> InstagramSource:
    if settings.resolved_source() == "fake":
        from app.infrastructure.instagram.fake_source import FakeInstagramSource

        return FakeInstagramSource()
    from app.infrastructure.instagram.instagrapi_source import InstagrapiInstagramSource

    return InstagrapiInstagramSource(settings)
