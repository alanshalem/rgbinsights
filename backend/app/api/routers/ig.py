"""Instagram session: connection status + reconnect (no terminal needed).

The source is instagrapi: it authenticates from a saved session, the pasted
IG_SESSIONID, or user+password (see InstagrapiInstagramSource._login).
  - POST /ig/reauth      re-runs that layered login (drops the cached session).
  - POST /ig/sessionid   adopts a fresh browser sessionid and persists it.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.api.deps import raise_for_instagram_error, session_dep
from app.api.schemas import IgSessionIdIn, IgStatusOut
from app.infrastructure.config.settings import Settings, get_settings
from app.infrastructure.instagram.base import InstagramSource
from app.infrastructure.instagram.errors import ChallengeRequiredError, InstagramError
from app.infrastructure.instagram.instagrapi_source import classify_login_error
from app.infrastructure.instagram.shared import get_shared_source, reset_shared_source
from app.infrastructure.persistence.repositories import AppStateRepository

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ig", tags=["instagram"])

_LAST_OK = "ig_last_ok_at"


def _source(settings: Settings) -> InstagramSource:
    # The shared (process-wide) source, so the status reflects the real session.
    return get_shared_source(settings.resolved_source())


def _no_challenge(username: str, choice: Any) -> str:
    raise ChallengeRequiredError("Instagram pidió verificación (challenge).")


def _status(session: Session, settings: Settings) -> IgStatusOut:
    """Read the live session and build the status payload (never raises)."""
    state = AppStateRepository(session)
    src = settings.resolved_source()
    demo = src == "fake"
    has_creds = bool(settings.ig_username.strip() and settings.ig_password.strip())
    pk: str | None = None
    try:
        pk = _source(settings).current_user_pk()
    except Exception:  # noqa: BLE001 — status must never 500: any fault = disconnected
        # Not just InstagramError: a dead source can raise network errors. If those
        # escaped, /ig/status would 500 and the IG chip would vanish from the UI
        # entirely (it hides when status can't load).
        logger.warning("ig_status: could not read session, reporting disconnected", exc_info=True)
        pk = None
    connected = bool(pk)
    if connected:
        state.set_dt(_LAST_OK, datetime.now(UTC))
        session.commit()
    return IgStatusOut(
        state="connected" if connected else "disconnected",
        pk=pk,
        last_ok_at=state.get_dt(_LAST_OK),
        demo=demo,
        source=src,
        has_credentials=has_creds,
    )


@router.get("/status", response_model=IgStatusOut)
def ig_status(
    session: Session = Depends(session_dep),
    settings: Settings = Depends(get_settings),
) -> IgStatusOut:
    return _status(session, settings)


@router.post("/reauth", response_model=IgStatusOut)
def ig_reauth(
    session: Session = Depends(session_dep),
    settings: Settings = Depends(get_settings),
) -> IgStatusOut:
    """Re-establish the session: saved session -> sessionid -> user/pass.

    Drops the cached source so the next call re-runs the full layered login.
    """
    reset_shared_source()
    try:
        _source(settings).current_user_pk()
    except InstagramError as exc:
        raise_for_instagram_error(exc)
    return _status(session, settings)


@router.post("/sessionid", response_model=IgStatusOut)
def ig_set_sessionid(
    body: IgSessionIdIn,
    session: Session = Depends(session_dep),
    settings: Settings = Depends(get_settings),
) -> IgStatusOut:
    """Adopt a sessionid pasted from a real browser: validate + persist to session.json."""
    sid = body.sessionid.strip()
    if not sid:
        raise HTTPException(400, detail={"code": "bad_request", "message": "sessionid vacío"})
    from app.infrastructure.instagram.session import build_client

    try:
        client = build_client(settings, _no_challenge)
        client.login_by_sessionid(sid)
        client.dump_settings(Path(settings.ig_session_file))
    except InstagramError as exc:  # already classified (e.g. challenge handler)
        raise_for_instagram_error(exc)
    except Exception as exc:  # noqa: BLE001 — classify IP-block vs expired session
        raise_for_instagram_error(classify_login_error(exc))
    reset_shared_source()  # next call reloads the now-valid session.json
    return _status(session, settings)
