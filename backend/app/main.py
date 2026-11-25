"""FastAPI app entrypoint. Binds to 127.0.0.1 only (see README) — never exposed."""

from __future__ import annotations

import logging
import signal
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import FrameType
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import (
    admin,
    avatars,
    campaigns,
    events,
    health,
    ig,
    posts,
    scan,
    sync,
    tasks,
    users,
)
from app.application import campaign_sender
from app.infrastructure.persistence.db import create_db_and_tables

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
)


def _stop_streams_on_exit_signals() -> None:
    """uvicorn waits for every open response before it exits or reloads (and on
    Windows `--reload` stops the worker with Ctrl+C): an SSE stream never ends by
    itself, so the shutdown signal ends it first, then uvicorn handles the signal
    as always. Background jobs are daemon threads: they never hold the exit."""
    if threading.current_thread() is not threading.main_thread():
        return  # signal handlers can only be set from the main thread
    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        sig = getattr(signal, name, None)
        previous = signal.getsignal(sig) if sig is not None else None
        if sig is None or not callable(previous):
            continue  # default/ignored: not a server that waits on responses

        def chained(signum: int, frame: FrameType | None, previous: Any = previous) -> None:
            tasks.stop_streams()
            previous(signum, frame)

        signal.signal(sig, chained)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    create_db_and_tables()
    campaign_sender.resume_all()  # resume any campaign left running
    _stop_streams_on_exit_signals()
    yield
    tasks.stop_streams()


app = FastAPI(
    title="RGB Collective — Instagram Semáforo",
    version="0.1.0",
    lifespan=lifespan,
)

# Local-only tool: the Vite dev server (5173) talks to this API on localhost.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(events.router)
app.include_router(campaigns.router)
app.include_router(scan.router)
app.include_router(sync.router)
app.include_router(users.router)
app.include_router(posts.router)
app.include_router(tasks.router)  # /tasks (+ /stream SSE) + /activity
app.include_router(admin.router)  # /reset (danger zone)
app.include_router(ig.router)  # /ig/status + reconnect (session)
app.include_router(avatars.router)  # /avatar/{pk} — cached profile pics
