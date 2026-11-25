"""FastAPI dependencies (from the composition root) + Result->HTTP mapping +
starting background jobs."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from typing import Any, NoReturn

from fastapi import Depends, HTTPException, Response
from sqlmodel import Session

from app import bootstrap
from app.api.schemas import TaskOut
from app.application.campaign_sender import CampaignSender
from app.application.ports import InstagramSource, UnitOfWork, UnitOfWorkFactory
from app.application.tasks import JobConflictError, JobWork, TaskView
from app.application.use_cases import map_instagram_error
from app.bootstrap import InstagramAccess
from app.domain.errors import InstagramError
from app.domain.result import Err, ErrorCode
from app.infrastructure.config.settings import Settings, get_settings
from app.infrastructure.persistence.repositories import EventRepository

_STATUS_BY_CODE = {
    ErrorCode.POST_NOT_FOUND: 404,
    ErrorCode.CHALLENGE_REQUIRED: 409,
    ErrorCode.LOGIN_REQUIRED: 401,
    ErrorCode.IP_BLOCKED: 403,
    ErrorCode.RATE_LIMITED: 429,
    ErrorCode.SEND_BLOCKED: 429,
    ErrorCode.UNKNOWN: 502,
}

# The current UI (Toasts.tsx) still reads a job's warning from result["aviso"];
# kept until it reads TaskOut.warning.
LEGACY_WARNING_KEY = "aviso"

SessionFactory = Callable[[], Session]


def session_dep() -> Iterator[Session]:
    with bootstrap.new_session() as session:
        yield session


def session_factory_dep() -> SessionFactory:
    """Opens new sessions for work that outlives the request (a job's worker
    thread): the request's own session is closed once the 202 is sent."""
    return bootstrap.new_session


def uow_dep(session: Session = Depends(session_dep)) -> UnitOfWork:
    return bootstrap.unit_of_work(session)


def uow_factory_dep(
    new_session: SessionFactory = Depends(session_factory_dep),
) -> UnitOfWorkFactory:
    """New units of work for a job's worker thread (see session_factory_dep)."""
    return lambda: bootstrap.unit_of_work(new_session())


def instagram_dep() -> InstagramAccess:
    return bootstrap.instagram


def source_dep(
    settings: Settings = Depends(get_settings),
    instagram: InstagramAccess = Depends(instagram_dep),
) -> InstagramSource:
    return instagram.source(settings)


def campaign_sender_dep() -> CampaignSender:
    return bootstrap.campaign_sender


def require_event(session: Session, event_id: int) -> None:
    """404 (`fiesta`) unless the event exists."""
    if EventRepository(session).get(event_id) is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "fiesta"})


def raise_for_err(err: Err) -> NoReturn:
    """Turn an expected-failure Result into a clean HTTP error with a code."""
    status = _STATUS_BY_CODE.get(err.code, 502)
    raise HTTPException(status_code=status, detail={"code": err.code.value, "message": err.message})


def raise_for_instagram_error(exc: InstagramError) -> NoReturn:
    """Map an adapter exception to its HTTP error — the single place routers use,
    so a challenge/login/rate-limit always gets the same status everywhere."""
    raise_for_err(map_instagram_error(exc))


def task_out(view: TaskView) -> TaskOut:
    out = TaskOut.model_validate(view, from_attributes=True)
    if view.warning:
        out.result = {**out.result, LEGACY_WARNING_KEY: view.warning}
    return out


def start_job(
    *,
    kind: str,
    label: str,
    params: dict[str, Any],
    work: JobWork,
    new_uow: UnitOfWorkFactory,
    response: Response,
) -> TaskOut:
    """Start a background job; the route answers 202 with it (Location: /tasks/{id}).

    While another Instagram job runs: the same kind + params get that running
    job back; anything else is a 409 (never queued, never run in parallel).
    Inside `work`, `task.unwrap(result)` ends the job as failed on an Err.
    """
    key = f"{kind}:{json.dumps(params, sort_keys=True, default=str)}"
    try:
        view = bootstrap.registry.start(kind, label, key, work, new_uow)
    except JobConflictError as exc:
        raise HTTPException(409, detail={"code": "conflict", "message": str(exc)}) from exc
    response.headers["Location"] = f"/tasks/{view.id}"
    return task_out(view)
