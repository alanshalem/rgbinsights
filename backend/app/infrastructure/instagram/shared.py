"""Process-wide singleton source, shared by the API and the campaign sender so
they drive the SAME browser (one Chrome), not two on the same locked profile."""

from __future__ import annotations

from functools import lru_cache

from app.infrastructure.config.settings import get_settings
from app.infrastructure.instagram.base import InstagramSource
from app.infrastructure.instagram.factory import build_source


@lru_cache
def get_shared_source(source: str) -> InstagramSource:
    return build_source(get_settings())
