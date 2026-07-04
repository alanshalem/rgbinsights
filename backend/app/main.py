"""FastAPI app entrypoint. Binds to 127.0.0.1 only (see README) — never exposed."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import (
    admin,
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


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    create_db_and_tables()
    campaign_sender.resume_all()  # resume any campaign left running
    yield


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
app.include_router(tasks.router)  # /tasks + /activity
app.include_router(admin.router)  # /reset (danger zone)
app.include_router(ig.router)  # /ig/status + /ig/login (session)
