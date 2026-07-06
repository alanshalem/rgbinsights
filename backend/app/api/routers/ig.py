"""Instagram session: connection status + reconnect (no terminal needed).

Reconnect is source-aware:
  - instagrapi (recommended): POST /ig/reauth re-logs in from .env credentials /
    saved session; POST /ig/sessionid pastes a fresh browser sessionid.
  - playwright (legacy): POST /ig/login opens a headed Chrome. Kept for that
    source only — its sessions are unreliable against IG (see the README).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.api.deps import raise_for_err, session_dep
from app.api.schemas import IgLoginOut, IgSessionIdIn, IgStatusOut
from app.domain.result import Err, ErrorCode
from app.infrastructure.config.settings import Settings, get_settings
from app.infrastructure.instagram import ig_login
from app.infrastructure.instagram.base import InstagramSource
from app.infrastructure.instagram.errors import ChallengeRequiredError, InstagramError
from app.infrastructure.instagram.shared import get_shared_source, reset_shared_source
from app.infrastructure.persistence.repositories import AppStateRepository

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ig", tags=["instagram"])

_LAST_OK = "ig_last_ok_at"


def _source(settings: Settings) -> InstagramSource:
    # Not via source_dep: that returns a throwaway Fake; here we want the shared
    # (real) source so the status reflects the actual session.
    src = settings.resolved_source()
    if src == "fake":
        from app.infrastructure.instagram.fake_source import FakeInstagramSource

        return FakeInstagramSource()
    return get_shared_source(src)


def _no_challenge(username: str, choice: Any) -> str:
    raise ChallengeRequiredError("Instagram pidió verificación (challenge).")


def _status(session: Session, settings: Settings) -> IgStatusOut:
    """Read the live session and build the status payload (never raises)."""
    state = AppStateRepository(session)
    src = settings.resolved_source()
    demo = src == "fake"
    has_creds = bool(settings.ig_username.strip() and settings.ig_password.strip())
    if ig_login.in_progress():
        return IgStatusOut(
            state="logging_in", pk=None, last_ok_at=state.get_dt(_LAST_OK),
            demo=demo, source=src, has_credentials=has_creds,
        )
    pk: str | None = None
    try:
        pk = _source(settings).current_user_pk()
    except Exception:  # noqa: BLE001 — status must never 500: any fault = disconnected
        # Not just InstagramError: a dead source can raise network/OS errors. If
        # those escaped, /ig/status would 500 and the IG chip would vanish from
        # the UI entirely (it hides when status can't load).
        logger.warning("ig_status: could not read session, reporting disconnected", exc_info=True)
        pk = None
    connected = bool(pk)
    if connected:
        state.set_dt(_LAST_OK, datetime.now(UTC))
        session.commit()
    return IgStatusOut(
        state="connected" if connected else "disconnected",
        pk=pk, last_ok_at=state.get_dt(_LAST_OK),
        demo=demo, source=src, has_credentials=has_creds,
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
    """Re-establish the session (instagrapi): saved session -> sessionid -> user/pass.

    Drops the cached source so the next call re-runs the full layered login.
    """
    reset_shared_source()
    try:
        _source(settings).current_user_pk()
    except ChallengeRequiredError as exc:
        raise_for_err(Err(ErrorCode.CHALLENGE_REQUIRED, str(exc)))
    except InstagramError as exc:
        raise_for_err(Err(ErrorCode.LOGIN_REQUIRED, str(exc)))
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
    except Exception as exc:  # noqa: BLE001 — surfaced as a handled error
        raise_for_err(Err(ErrorCode.LOGIN_REQUIRED, f"sessionid inválido o vencido: {exc}"))
    reset_shared_source()  # next call reloads the now-valid session.json
    return _status(session, settings)


@router.post("/login", response_model=IgLoginOut)
def ig_login_start(settings: Settings = Depends(get_settings)) -> IgLoginOut:
    """Legacy playwright path: open a headed Chrome so the user logs in by hand."""
    if settings.resolved_source() != "playwright":
        raise HTTPException(
            400,
            detail={"code": "bad_request", "message": "reconexión por navegador es solo en modo playwright"},
        )
    try:
        ig_login.start(settings)
    except FileNotFoundError as exc:
        raise HTTPException(400, detail={"code": "bad_request", "message": str(exc)}) from exc
    return IgLoginOut(opened=True, logged_in=False)


@router.post("/login/finish", response_model=IgLoginOut)
def ig_login_finish(
    session: Session = Depends(session_dep),
    settings: Settings = Depends(get_settings),
) -> IgLoginOut:
    """Poll: closes the login window and confirms once the user is logged in."""
    pk = ig_login.finish(settings)
    if pk:
        # finish() saved the login cookies; the headless browser re-seeds from
        # them (with a de-headlessed UA) when it next starts, so it authenticates.
        AppStateRepository(session).set_dt(_LAST_OK, datetime.now(UTC))
        session.commit()
    return IgLoginOut(opened=ig_login.in_progress(), logged_in=bool(pk))
