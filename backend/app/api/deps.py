"""FastAPI dependencies + Result->HTTP mapping + starting background jobs."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any, NoReturn

from fastapi import Depends, HTTPException, Response
from sqlmodel import Session

from app.api.schemas import TaskOut
from app.application.tasks import JobConflictError, JobWork, SessionFactory, Task, registry
from app.application.use_cases import map_instagram_error
from app.domain.result import Err, ErrorCode
from app.infrastructure.config.settings import Settings, get_settings
from app.infrastructure.instagram.base import InstagramSource
from app.infrastructure.instagram.errors import InstagramError
from app.infrastructure.instagram.fake_source import FakeInstagramSource
from app.infrastructure.instagram.shared import get_shared_source
from app.infrastructure.persistence.db import engine, get_session

_STATUS_BY_CODE = {
    ErrorCode.POST_NOT_FOUND: 404,
    ErrorCode.CHALLENGE_REQUIRED: 409,
    ErrorCode.LOGIN_REQUIRED: 401,
    ErrorCode.IP_BLOCKED: 403,
    ErrorCode.RATE_LIMITED: 429,
    ErrorCode.SEND_BLOCKED: 429,
    ErrorCode.UNKNOWN: 502,
}


# A failed job's message is shown as is: Spanish, even where the adapter's is not.
_JOB_MESSAGE_BY_CODE = {
    ErrorCode.POST_NOT_FOUND: "No se encontró el post (borrado, privado o link inválido).",
    ErrorCode.CHALLENGE_REQUIRED: "Instagram pide verificación: reconectá desde el chip IG.",
    ErrorCode.LOGIN_REQUIRED: "La sesión de Instagram se cerró: reconectá desde el chip IG.",
    ErrorCode.IP_BLOCKED: "Instagram bloqueó la conexión (IP), no la sesión.",
    ErrorCode.RATE_LIMITED: "Instagram pidió frenar: probá de nuevo más tarde.",
    ErrorCode.SEND_BLOCKED: "Instagram bloqueó el envío de mensajes.",
    ErrorCode.UNKNOWN: "Falló la operación con Instagram.",
}
# Codes whose adapter message is not Spanish: always the message above.
_FIXED_JOB_MESSAGE = {ErrorCode.POST_NOT_FOUND}


def session_dep() -> Iterator[Session]:
    yield from get_session()


def _new_session() -> Session:
    return Session(engine)


def session_factory_dep() -> SessionFactory:
    """Opens new sessions for work that outlives the request (a job's worker
    thread): the request's own session is closed once the 202 is sent."""
    return _new_session


def source_dep(settings: Settings = Depends(get_settings)) -> InstagramSource:
    source = settings.resolved_source()
    if source == "fake":
        return FakeInstagramSource()
    return get_shared_source(source)


def raise_for_err(err: Err) -> NoReturn:
    """Turn an expected-failure Result into a clean HTTP error with a code."""
    status = _STATUS_BY_CODE.get(err.code, 502)
    raise HTTPException(status_code=status, detail={"code": err.code.value, "message": err.message})


def start_job(
    *,
    kind: str,
    label: str,
    params: dict[str, Any],
    work: JobWork,
    session_factory: SessionFactory,
    response: Response,
) -> TaskOut:
    """Start a background job; the route answers 202 with it (Location: /tasks/{id}).

    While another Instagram job runs: the same kind + params get that running
    job back; anything else is a 409 (never queued, never run in parallel).
    """
    key = f"{kind}:{json.dumps(params, sort_keys=True, default=str)}"
    try:
        task = registry.start(kind, label, key, work, session_factory)
    except JobConflictError as exc:
        raise HTTPException(409, detail={"code": "conflict", "message": str(exc)}) from exc
    response.headers["Location"] = f"/tasks/{task.id}"
    return TaskOut.model_validate(task, from_attributes=True)


def fail_job(task: Task, err: Err) -> None:
    """Record an expected failure (Result.Err) on the job, in Spanish."""
    fallback = _JOB_MESSAGE_BY_CODE.get(err.code, _JOB_MESSAGE_BY_CODE[ErrorCode.UNKNOWN])
    message = fallback if err.code in _FIXED_JOB_MESSAGE else (err.message or fallback)
    task.fail(message, err.code.value)


def raise_for_instagram_error(exc: InstagramError) -> NoReturn:
    """Map an adapter exception to its HTTP error — the single place routers use,
    so a challenge/login/rate-limit always gets the same status everywhere."""
    raise_for_err(map_instagram_error(exc))
