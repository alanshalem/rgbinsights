"""Instagram session: connection status + reconnect (no terminal needed).

The source is instagrapi: it authenticates from a saved session, the pasted
IG_SESSIONID, or user+password (see IgLogin.client_or_login).
  - GET  /ig/status      last known state only — never logs in, never calls IG.
  - POST /ig/reauth      re-runs that layered login (drops the cached session).
  - POST /ig/sessionid   adopts a fresh browser sessionid and persists it.
Logins are gated by the guard's circuit breaker (guard.py).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.api.deps import instagram_dep, raise_for_instagram_error, session_dep
from app.api.schemas import IgSessionIdIn, IgStatusOut
from app.bootstrap import InstagramAccess
from app.domain.errors import InstagramError
from app.infrastructure.config.settings import Settings, get_settings
from app.infrastructure.persistence.repositories import AppStateRepository

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ig", tags=["instagram"])

_LAST_OK = "ig_last_ok_at"


def _status(
    session: Session, settings: Settings, instagram: InstagramAccess, pk: str | None
) -> IgStatusOut:
    """Build the status payload from what is already known (no Instagram call)."""
    state = AppStateRepository(session)
    demo = settings.is_fake
    cooldown_until = last_error = None
    if demo:
        if pk:
            state.set_dt(_LAST_OK, datetime.now(UTC))
            session.commit()
        last_ok_at = state.get_dt(_LAST_OK)
    else:
        snap = instagram.guard(settings).snapshot()
        pk = None if snap.breaker_open else pk  # a failed login is being waited out
        cooldown_until, last_error = snap.blocked_until, snap.last_error
        last_ok_at = snap.last_ok_at or state.get_dt(_LAST_OK)
    return IgStatusOut(
        state="connected" if pk else "disconnected",
        pk=pk,
        last_ok_at=last_ok_at,
        demo=demo,
        source=settings.ig_source,
        has_credentials=settings.has_password_login,
        cooldown_until=cooldown_until,
        last_error=last_error,
    )


def _live_status(session: Session, settings: Settings, instagram: InstagramAccess) -> IgStatusOut:
    pk = instagram.source(settings).cached_user_pk()  # demo: the fake, always connected
    return _status(session, settings, instagram, pk)


@router.get("/status", response_model=IgStatusOut)
def ig_status(
    session: Session = Depends(session_dep),
    settings: Settings = Depends(get_settings),
    instagram: InstagramAccess = Depends(instagram_dep),
) -> IgStatusOut:
    """Polled by the UI every 20 s, so it must never log in: a failed login
    retried on every poll is exactly what gets an account flagged."""
    return _live_status(session, settings, instagram)


@router.post("/reauth", response_model=IgStatusOut)
def ig_reauth(
    session: Session = Depends(session_dep),
    settings: Settings = Depends(get_settings),
    instagram: InstagramAccess = Depends(instagram_dep),
) -> IgStatusOut:
    """Re-establish the session: saved session -> sessionid -> user/pass.

    Drops the cached source so the next call re-runs the full layered login
    (refused while the login breaker is open).
    """
    instagram.reset()
    try:
        instagram.source(settings).current_user_pk()
    except InstagramError as exc:
        raise_for_instagram_error(exc)
    return _live_status(session, settings, instagram)


@router.post("/disconnect", response_model=IgStatusOut)
def ig_disconnect(
    session: Session = Depends(session_dep),
    settings: Settings = Depends(get_settings),
    instagram: InstagramAccess = Depends(instagram_dep),
) -> IgStatusOut:
    """Forget the saved session: delete session.json + drop the cached source.

    A UI-pasted session is fully cleared. If .env still has IG_SESSIONID or
    user/pass, the next explicit reconnect (or IG operation) logs in from those
    (they are configured credentials, not the saved cookie).
    """
    Path(settings.ig_session_file).unlink(missing_ok=True)
    logger.info("disconnected IG: removed %s", settings.ig_session_file)
    instagram.reset()
    return _status(session, settings, instagram, None)  # report disconnected immediately


@router.post("/sessionid", response_model=IgStatusOut)
def ig_set_sessionid(
    body: IgSessionIdIn,
    session: Session = Depends(session_dep),
    settings: Settings = Depends(get_settings),
    instagram: InstagramAccess = Depends(instagram_dep),
) -> IgStatusOut:
    """Adopt a sessionid pasted from a real browser: validate + persist to session.json."""
    sid = body.sessionid.strip()
    if not sid:
        raise HTTPException(400, detail={"code": "bad_request", "message": "sessionid vacío"})
    try:
        instagram.source(settings).connect_sessionid(sid)
    except InstagramError as exc:
        raise_for_instagram_error(exc)
    return _live_status(session, settings, instagram)
