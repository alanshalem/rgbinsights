from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import AsyncGenerator, Callable

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlmodel import Session, col, select

from app.api.deps import session_dep, task_out
from app.api.schemas import ActivityOut, StatusOut, TaskOut
from app.application.tasks import TaskRegistry
from app.application.use_cases import KEY_DMS_SYNCED, KEY_RELATIONS_SYNCED
from app.bootstrap import registry
from app.infrastructure.persistence import models
from app.infrastructure.persistence.repositories import AppStateRepository

router = APIRouter(tags=["tasks"])

HEARTBEAT_SECONDS = 15.0
# How often an idle stream re-checks that the server is not shutting down.
_STOP_CHECK_SECONDS = 1.0
_RETRY_MS = 3000  # EventSource reconnect delay after the stream ends

_stopping = threading.Event()


def stop_streams() -> None:
    """End every open SSE stream (server shutdown / reload). Signal-safe: only
    sets a flag, which each stream checks at least once a second."""
    _stopping.set()


def streams_stopped() -> bool:
    return _stopping.is_set()


def reset_streams() -> None:
    """Allow streams again (server startup): a stop flag left set by an earlier
    shutdown in this process would end every new stream at once."""
    _stopping.clear()


@router.get("/status", response_model=StatusOut)
def status(session: Session = Depends(session_dep)) -> StatusOut:
    """Freshness of the shared data, for the 'actualizado hace Xh' hints."""
    state = AppStateRepository(session)
    return StatusOut(
        relationships_synced_at=state.get_dt(KEY_RELATIONS_SYNCED),
        dms_synced_at=state.get_dt(KEY_DMS_SYNCED),
    )


@router.get("/tasks", response_model=list[TaskOut])
def list_tasks() -> list[TaskOut]:
    """Polling fallback of /tasks/stream (same snapshots)."""
    return [task_out(t) for t in registry.list()]


@router.get(
    "/tasks/stream",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}}},
)
def stream_tasks() -> StreamingResponse:
    """Server-Sent Events: an `event: tasks` with every task (the same list as
    GET /tasks) on connect and on every change, plus a `: ping` comment every
    15 s while idle. Reads memory only: never touches Instagram or the DB."""
    return StreamingResponse(
        task_events(stopped=streams_stopped),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/tasks/{task_id}", response_model=TaskOut)
def get_task(task_id: str) -> TaskOut:
    task = registry.get(task_id)
    if task is None:
        raise HTTPException(
            404, detail={"code": "not_found", "message": "tarea no encontrada (terminó hace rato?)"}
        )
    return task_out(task)


@router.get("/activity", response_model=list[ActivityOut])
def list_activity(
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(session_dep),
) -> list[ActivityOut]:
    rows = session.exec(
        select(models.ActivityLog).order_by(col(models.ActivityLog.id).desc()).limit(limit)
    )
    return [ActivityOut.model_validate(r, from_attributes=True) for r in rows]


def _tasks_event(reg: TaskRegistry) -> str:
    data = json.dumps([task_out(t).model_dump(mode="json") for t in reg.list()])
    return f"event: tasks\ndata: {data}\n\n"


async def task_events(
    *,
    registry: TaskRegistry = registry,
    heartbeat: float = HEARTBEAT_SECONDS,
    stopped: Callable[[], bool] = streams_stopped,
) -> AsyncGenerator[str]:
    """The SSE body: the task list now and after each change, a heartbeat while
    idle; ends when `stopped()` (so a shutdown/reload never waits on it)."""
    loop = asyncio.get_running_loop()
    version = registry.version  # read before the list: a change in between is resent
    yield f"retry: {_RETRY_MS}\n" + _tasks_event(registry)
    last_sent = loop.time()
    while not stopped():
        idle = loop.time() - last_sent
        if idle >= heartbeat:
            yield ": ping\n\n"
            last_sent = loop.time()
            continue
        wait = min(_STOP_CHECK_SECONDS, heartbeat - idle)
        if await registry.wait_for_change(version, wait) != version:
            version = registry.version
            yield _tasks_event(registry)
            last_sent = loop.time()
