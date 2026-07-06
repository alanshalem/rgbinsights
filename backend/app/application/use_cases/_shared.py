"""Cross-use-case helpers: time, error mapping, small DTO builders."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from app.application.dto import ScannedPost, StatusCounts
from app.domain.entities import Post
from app.domain.result import Err, ErrorCode
from app.infrastructure.instagram.errors import (
    ChallengeRequiredError,
    InstagramError,
    LoginRequiredError,
    PostNotFoundError,
    RateLimitedError,
)

ProgressFn = Callable[..., None]

# app_state keys for cache/TTL timestamps.
KEY_DMS_SYNCED = "dms_synced_at"
KEY_RELATIONS_SYNCED = "relationships_synced_at"


def _now() -> datetime:
    return datetime.now(UTC)


def _naive(dt: datetime | None) -> datetime | None:
    """Drop tzinfo so DB-read (naive) and API (maybe aware) datetimes compare."""
    return dt.replace(tzinfo=None) if dt is not None and dt.tzinfo is not None else dt


def map_instagram_error(exc: InstagramError) -> Err:
    if isinstance(exc, PostNotFoundError):
        return Err(ErrorCode.POST_NOT_FOUND, "post not found")
    if isinstance(exc, ChallengeRequiredError):
        return Err(ErrorCode.CHALLENGE_REQUIRED, str(exc))
    if isinstance(exc, LoginRequiredError):
        return Err(ErrorCode.LOGIN_REQUIRED, str(exc))
    if isinstance(exc, RateLimitedError):
        return Err(ErrorCode.RATE_LIMITED, str(exc))
    return Err(ErrorCode.UNKNOWN, str(exc))


def _to_scanned(post: Post) -> ScannedPost:
    return ScannedPost(
        media_pk=post.media_pk,
        shortcode=post.shortcode,
        url=post.url,
        caption=post.caption,
        taken_at=post.taken_at,
    )


def state_delta(before: StatusCounts, after: StatusCounts) -> dict[str, int]:
    """Positive state transitions between two snapshots, for the 'qué cambió' toast.

    respondieron  = new greens (someone replied → green)
    amarillos     = net new yellows (contacted, no reply yet)
    Only positive moves are reported; a quiet sync yields an empty dict.
    """
    out: dict[str, int] = {}
    if (respondieron := after.green - before.green) > 0:
        out["respondieron"] = respondieron
    if (amarillos := after.yellow - before.yellow) > 0:
        out["amarillos"] = amarillos
    return out
