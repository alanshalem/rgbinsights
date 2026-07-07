"""Process-wide singleton source, shared by the API and the campaign sender so
they reuse the SAME instagrapi session (one login, one device) instead of each
building its own."""

from __future__ import annotations

from functools import lru_cache

from app.infrastructure.config.settings import get_settings
from app.infrastructure.instagram.base import InstagramSource
from app.infrastructure.instagram.factory import build_source

_current: InstagramSource | None = None


@lru_cache
def get_shared_source(source: str) -> InstagramSource:
    global _current
    _current = build_source(get_settings())
    return _current


def reset_shared_source() -> None:
    """Dispose the shared source and forget it, so the next call rebuilds a fresh
    one. Used after an in-app reconnect/disconnect: drop the cached session so
    the next Instagram op picks up the new (or absent) session.json."""
    global _current
    if _current is not None:
        dispose = getattr(_current, "dispose", None)
        if callable(dispose):
            dispose()
    _current = None
    get_shared_source.cache_clear()
