"""Instagram session: connection status + in-app login (no terminal needed)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.api.deps import session_dep
from app.api.schemas import IgLoginOut, IgStatusOut
from app.infrastructure.config.settings import Settings, get_settings
from app.infrastructure.instagram import ig_login
from app.infrastructure.instagram.base import InstagramSource
from app.infrastructure.instagram.shared import get_shared_source
from app.infrastructure.persistence.repositories import AppStateRepository

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ig", tags=["instagram"])

_LAST_OK = "ig_last_ok_at"


def _source(settings: Settings) -> InstagramSource:
    # Not via source_dep: that returns a throwaway Fake; here we want the shared
    # (real) browser so the status reflects the actual session.
    src = settings.resolved_source()
    if src == "fake":
        from app.infrastructure.instagram.fake_source import FakeInstagramSource

        return FakeInstagramSource()
    return get_shared_source(src)


@router.get("/status", response_model=IgStatusOut)
def ig_status(
    session: Session = Depends(session_dep),
    settings: Settings = Depends(get_settings),
) -> IgStatusOut:
    state = AppStateRepository(session)
    demo = settings.resolved_source() == "fake"
    if ig_login.in_progress():
        return IgStatusOut(
            state="logging_in", pk=None, last_ok_at=state.get_dt(_LAST_OK), demo=demo
        )
    pk: str | None = None
    try:
        pk = _source(settings).current_user_pk()
    except Exception:  # noqa: BLE001 — status must never 500: any fault = disconnected
        # Not just InstagramError: a dead/unreachable browser raises Playwright/OS
        # errors here. If those escaped, /ig/status would 500 and the IG chip would
        # vanish from the UI entirely (it hides when status can't load).
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
    )


@router.post("/login", response_model=IgLoginOut)
def ig_login_start(settings: Settings = Depends(get_settings)) -> IgLoginOut:
    """Open a headed Chrome so the user logs into Instagram by hand."""
    if settings.resolved_source() != "playwright":
        raise HTTPException(
            400,
            detail={"code": "bad_request", "message": "el login es solo en modo Instagram real"},
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
        AppStateRepository(session).set_dt(_LAST_OK, datetime.now(UTC))
        session.commit()
    return IgLoginOut(opened=ig_login.in_progress(), logged_in=bool(pk))
