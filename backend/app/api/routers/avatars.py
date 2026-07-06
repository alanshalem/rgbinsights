"""Avatar proxy + cache.

Instagram profile-pic URLs are signed CDN links that expire in hours/days, so
the browser eventually shows broken images. This downloads each pic ONCE (while
its URL is still valid) into a local cache and serves it from there forever —
the <img> points at us, not at the expiring CDN link.
"""

from __future__ import annotations

import logging
from pathlib import Path

import requests
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response
from sqlmodel import Session

from app.api.deps import session_dep
from app.infrastructure.persistence import models

logger = logging.getLogger(__name__)
router = APIRouter(tags=["avatars"])

_CACHE_DIR = Path("avatar_cache")
_CACHE_DIR.mkdir(exist_ok=True)
# Cache hard in the browser too; the bytes for a pk never change once stored.
_CACHE_HEADERS = {"Cache-Control": "public, max-age=604800"}  # 7 days


@router.get("/avatar/{pk}")
def avatar(pk: str, session: Session = Depends(session_dep)) -> Response:
    """Serve a user's profile pic from the local cache, downloading it once."""
    if not pk.isdigit():  # IG pks are numeric — also guards against path traversal
        raise HTTPException(status_code=404, detail="bad pk")

    cached = _CACHE_DIR / f"{pk}.jpg"
    if cached.exists():
        return FileResponse(cached, media_type="image/jpeg", headers=_CACHE_HEADERS)

    user = session.get(models.User, pk)
    if user is None or not user.profile_pic_url:
        raise HTTPException(status_code=404, detail="no avatar")

    try:
        resp = requests.get(user.profile_pic_url, timeout=10)
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001 — expired/blocked URL: 404 -> UI shows initials
        logger.info("avatar download failed for %s: %s", pk, exc)
        raise HTTPException(status_code=404, detail="avatar unavailable") from exc

    cached.write_bytes(resp.content)
    return Response(
        content=resp.content,
        media_type=resp.headers.get("content-type", "image/jpeg"),
        headers=_CACHE_HEADERS,
    )
