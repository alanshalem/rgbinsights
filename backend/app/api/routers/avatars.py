"""Avatar proxy + cache.

Instagram profile-pic URLs are signed CDN links that expire in hours/days, so
the browser eventually shows broken images. This downloads each pic ONCE (while
its URL is still valid) into a local cache and serves it from there forever —
the <img> points at us, not at the expiring CDN link. Downloads look like a
regular browser and leave through the same proxy as the Instagram client, so
the CDN sees one consistent visitor instead of a bare python-requests client.
A failed download is remembered for a while (negative cache) and each attempt
has a short timeout, so a dead proxy or URL can't pin threadpool workers.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

import requests
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response
from sqlmodel import Session

from app.api.deps import session_dep
from app.infrastructure.config.settings import Settings, get_settings
from app.infrastructure.persistence import models

logger = logging.getLogger(__name__)
router = APIRouter(tags=["avatars"])

_CACHE_DIR = Path("avatar_cache")
_CACHE_DIR.mkdir(exist_ok=True)
# Cache hard in the browser too; the bytes for a pk never change once stored.
_CACHE_HEADERS = {"Cache-Control": "public, max-age=604800"}  # 7 days
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
    "Referer": "https://www.instagram.com/",
}
_TIMEOUT_SECONDS = 4
_FAILURE_TTL_SECONDS = 600.0  # don't retry a failed avatar for 10 minutes
_failed: dict[str, float] = {}  # pk -> monotonic time until which we don't retry
_failed_lock = threading.Lock()


def _recently_failed(pk: str) -> bool:
    with _failed_lock:
        until = _failed.get(pk)
        if until is not None and time.monotonic() >= until:
            del _failed[pk]
            until = None
    return until is not None


def _remember_failure(pk: str) -> None:
    with _failed_lock:
        _failed[pk] = time.monotonic() + _FAILURE_TTL_SECONDS


@router.get("/avatar/{pk}")
def avatar(
    pk: str,
    session: Session = Depends(session_dep),
    settings: Settings = Depends(get_settings),
) -> Response:
    """Serve a user's profile pic from the local cache, downloading it once."""
    if not pk.isdigit():  # IG pks are numeric — also guards against path traversal
        raise HTTPException(status_code=404, detail="bad pk")

    cached = _CACHE_DIR / f"{pk}.jpg"
    if cached.exists():
        return FileResponse(cached, media_type="image/jpeg", headers=_CACHE_HEADERS)

    if _recently_failed(pk):
        raise HTTPException(status_code=404, detail="avatar unavailable")

    user = session.get(models.User, pk)
    if user is None or not user.profile_pic_url:
        raise HTTPException(status_code=404, detail="no avatar")

    proxy = settings.ig_proxy.strip()
    try:
        resp = requests.get(
            user.profile_pic_url,
            headers=_BROWSER_HEADERS,
            proxies={"http": proxy, "https": proxy} if proxy else None,
            timeout=_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001 — expired/blocked URL: 404 -> UI shows initials
        logger.info("avatar download failed for %s: %s", pk, exc)
        _remember_failure(pk)
        raise HTTPException(status_code=404, detail="avatar unavailable") from exc

    cached.write_bytes(resp.content)
    return Response(
        content=resp.content,
        media_type=resp.headers.get("content-type", "image/jpeg"),
        headers=_CACHE_HEADERS,
    )
