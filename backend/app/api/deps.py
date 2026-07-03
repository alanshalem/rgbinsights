"""FastAPI dependencies + Result->HTTP mapping."""

from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache
from typing import NoReturn

from fastapi import Depends, HTTPException
from sqlmodel import Session

from app.domain.result import Err, ErrorCode
from app.infrastructure.config.settings import Settings, get_settings
from app.infrastructure.instagram.base import InstagramSource
from app.infrastructure.instagram.fake_source import FakeInstagramSource
from app.infrastructure.persistence.db import get_session

_STATUS_BY_CODE = {
    ErrorCode.POST_NOT_FOUND: 404,
    ErrorCode.CHALLENGE_REQUIRED: 409,
    ErrorCode.LOGIN_REQUIRED: 401,
    ErrorCode.RATE_LIMITED: 429,
    ErrorCode.UNKNOWN: 502,
}


def session_dep() -> Iterator[Session]:
    yield from get_session()


@lru_cache
def _real_source(settings_id: int) -> InstagramSource:
    # Cache the real client per settings object so login/session is reused.
    from app.infrastructure.instagram.instagrapi_source import InstagrapiInstagramSource

    return InstagrapiInstagramSource(get_settings())


def source_dep(settings: Settings = Depends(get_settings)) -> InstagramSource:
    if settings.use_fake_instagram:
        return FakeInstagramSource()
    return _real_source(id(settings))


def raise_for_err(err: Err) -> NoReturn:
    """Turn an expected-failure Result into a clean HTTP error with a code."""
    status = _STATUS_BY_CODE.get(err.code, 502)
    raise HTTPException(status_code=status, detail={"code": err.code.value, "message": err.message})
