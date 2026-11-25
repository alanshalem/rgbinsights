"""Instagram session: connection status + reconnect (no terminal needed).

The only way in is a sessionid pasted in the app (L24), saved to session.json
and reused across restarts (see IgLogin).
  - GET  /ig/status      last known state only — never logs in, never calls IG.
  - POST /ig/reauth      "Volver a conectar": re-checks the saved session.json
                         once (one cheap probe; drops the cached session).
  - POST /ig/sessionid   adopts a fresh browser sessionid and persists it.
  - POST /ig/disconnect  forgets the saved session.
Every attempt is gated by the guard's circuit breaker (guard.py).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.api.deps import instagram_dep, raise_for_instagram_error, session_dep, settings_dep
from app.api.schemas import IgSessionIdIn, IgStatusOut
from app.bootstrap import InstagramAccess
from app.domain.errors import InstagramError
from app.infrastructure.config.settings import Settings
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
        has_saved_session=Path(settings.ig_session_file).exists(),
        cooldown_until=cooldown_until,
        last_error=last_error,
    )


def _live_status(session: Session, settings: Settings, instagram: InstagramAccess) -> IgStatusOut:
    pk = instagram.source(settings).cached_user_pk()  # dev fake source: always connected
    return _status(session, settings, instagram, pk)


@router.get("/status", response_model=IgStatusOut)
def ig_status(
    session: Session = Depends(session_dep),
    settings: Settings = Depends(settings_dep),
    instagram: InstagramAccess = Depends(instagram_dep),
) -> IgStatusOut:
    """Polled by the UI every 20 s, so it must never log in: a failed login
    retried on every poll is exactly what gets an account flagged."""
    return _live_status(session, settings, instagram)


@router.post("/reauth", response_model=IgStatusOut)
def ig_reauth(
    session: Session = Depends(session_dep),
    settings: Settings = Depends(settings_dep),
    instagram: InstagramAccess = Depends(instagram_dep),
) -> IgStatusOut:
    """Re-check the saved session: drop the cached source and probe
    session.json once (refused while the login breaker is open). No saved
    session: 401 without any request."""
    instagram.reset()
    try:
        instagram.source(settings).current_user_pk()
    except InstagramError as exc:
        raise_for_instagram_error(exc)
    return _live_status(session, settings, instagram)


@router.post("/disconnect", response_model=IgStatusOut)
def ig_disconnect(
    session: Session = Depends(session_dep),
    settings: Settings = Depends(settings_dep),
    instagram: InstagramAccess = Depends(instagram_dep),
) -> IgStatusOut:
    """Forget the saved session: delete session.json + drop the cached source.
    Connecting again needs a new pasted sessionid."""
    Path(settings.ig_session_file).unlink(missing_ok=True)
    logger.info("disconnected IG: removed %s", settings.ig_session_file)
    instagram.reset()
    return _status(session, settings, instagram, None)  # report disconnected immediately


@router.post("/sessionid", response_model=IgStatusOut)
def ig_set_sessionid(
    body: IgSessionIdIn,
    session: Session = Depends(session_dep),
    settings: Settings = Depends(settings_dep),
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
