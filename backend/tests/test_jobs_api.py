"""HTTP contract of the background jobs (S16): 202 + job id at once, the work in
a worker thread with its own DB session, one Instagram job at a time (S0).

Every test runs on FakeInstagramSource or a stub of it: no Instagram traffic.
"""

from __future__ import annotations

import asyncio
import json
import signal
import threading
import time
from collections.abc import Callable, Iterator, MutableMapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import pytest
from app.api.deps import session_dep, session_factory_dep, source_dep
from app.api.routers import tasks as tasks_router
from app.application.ports import InstagramSource
from app.application.use_cases import KEY_DMS_SYNCED
from app.application.use_cases.sync import CAPPED_NOTE
from app.bootstrap import registry
from app.domain.entities import DmInbox
from app.infrastructure.config.settings import Settings, get_settings
from app.infrastructure.instagram.fake_source import FakeInstagramSource
from app.infrastructure.persistence import db, models
from app.infrastructure.persistence.repositories import AppStateRepository
from app.main import app
from sqlalchemy import Engine
from sqlmodel import Session, col, select

_TIMEOUT = 10.0
POST_A = "https://instagram.com/p/Cabc123/"
POST_B = "https://instagram.com/p/Cdef456/"
BUSY = (
    "Ya hay una tarea con Instagram en curso («Sincronizando DMs»). "
    "Esperá a que termine y probá de nuevo."
)


class GatedSource(FakeInstagramSource):
    """Fake source whose DM read blocks until released: a job 'still running'."""

    def __init__(self) -> None:
        super().__init__()
        self.entered = threading.Event()
        self.release = threading.Event()
        self.dm_calls = 0

    def get_dm_threads(self, since: datetime | None = None) -> DmInbox:
        self.dm_calls += 1
        self.entered.set()
        assert self.release.wait(_TIMEOUT)
        return super().get_dm_threads(since)


class CrashingSource(FakeInstagramSource):
    def get_dm_threads(self, since: datetime | None = None) -> DmInbox:
        raise RuntimeError("boom")


class CappedSource(FakeInstagramSource):
    """An incremental read the DM_THREADS_LIMIT cut short."""

    def get_dm_threads(self, since: datetime | None = None) -> DmInbox:
        return DmInbox(threads=[], complete=False)


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    eng = db.build_engine(f"sqlite:///{tmp_path / 'jobs.db'}")
    db.create_db_and_tables(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def use_source(engine: Engine) -> Iterator[Callable[[InstagramSource], None]]:
    """Wire the app to the test DB + a given fake source; FakeInstagramSource by default."""
    settings = Settings(_env_file=None, use_fake_instagram=True, ig_source="")

    def session() -> Iterator[Session]:
        with Session(engine) as s:
            yield s

    def factory() -> Callable[[], Session]:
        return lambda: Session(engine)

    def use(source: InstagramSource) -> None:
        app.dependency_overrides[source_dep] = lambda: source

    app.dependency_overrides[session_dep] = session
    app.dependency_overrides[session_factory_dep] = factory
    app.dependency_overrides[get_settings] = lambda: settings
    use(FakeInstagramSource())
    try:
        yield use
    finally:
        _wait_idle()
        for dep in (session_dep, session_factory_dep, get_settings, source_dep):
            app.dependency_overrides.pop(dep, None)


def _wait_idle() -> None:
    deadline = time.monotonic() + _TIMEOUT
    while any(t.status == "running" for t in registry.list()):
        assert time.monotonic() < deadline, "a job never finished"
        time.sleep(0.01)


def _call(
    method: str, path: str, params: dict[str, Any] | None = None, body: Any = None
) -> tuple[int, dict[str, str], Any]:
    """Drive the ASGI app directly (no extra HTTP client dependency)."""
    messages: list[MutableMapping[str, Any]] = []
    raw = json.dumps(body).encode() if body is not None else b""
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "query_string": urlencode(params or {}).encode(),
        "headers": [(b"host", b"testserver"), (b"content-type", b"application/json")],
        "client": ("127.0.0.1", 1234),
        "server": ("testserver", 80),
    }

    sent_body = False

    async def receive() -> dict[str, Any]:
        nonlocal sent_body
        if not sent_body:
            sent_body = True
            return {"type": "http.request", "body": raw, "more_body": False}
        await asyncio.Event().wait()  # the client stays connected (until cancelled)
        return {"type": "http.disconnect"}

    async def send(message: MutableMapping[str, Any]) -> None:
        messages.append(message)

    asyncio.run(app(scope, receive, send))
    start = next(m for m in messages if m["type"] == "http.response.start")
    headers = {k.decode().lower(): v.decode() for k, v in start["headers"]}
    data = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
    if headers.get("content-type", "").startswith("application/json"):
        return start["status"], headers, json.loads(data)
    return start["status"], headers, data.decode()


def _event(engine: Engine) -> int:
    with Session(engine) as s:
        ev = models.Event(
            name="F",
            promo_start=datetime(2026, 6, 1, tzinfo=UTC),
            event_date=datetime(2026, 6, 30, tzinfo=UTC),
            created_at=datetime.now(UTC),
        )
        s.add(ev)
        s.commit()
        assert ev.id is not None
        return ev.id


def _finished(task_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + _TIMEOUT
    while True:
        status, _, body = _call("GET", f"/tasks/{task_id}")
        assert status == 200
        if body["status"] != "running":
            return dict(body)
        assert time.monotonic() < deadline, "job never finished"
        time.sleep(0.02)


def _started(status: int, headers: dict[str, str], body: Any, kind: str) -> str:
    assert status == 202, body
    assert body["kind"] == kind and body["status"] == "running"
    assert headers["location"] == f"/tasks/{body['id']}"
    return str(body["id"])


def _job_result(
    method: str, path: str, kind: str, params: dict[str, Any] | None = None, body: Any = None
) -> dict[str, Any]:
    return _finished(_started(*_call(method, path, params, body), kind))


def _activity(engine: Engine) -> list[tuple[str, str, str]]:
    with Session(engine) as s:
        rows = s.exec(select(models.ActivityLog).order_by(col(models.ActivityLog.id)))
        return [(r.kind, r.status, r.message) for r in rows]


# -- start / complete ---------------------------------------------------------


def test_sync_returns_202_with_the_job_before_the_work_ends(
    engine: Engine, use_source: Callable[[InstagramSource], None]
) -> None:
    source = GatedSource()
    use_source(source)
    task_id = _started(*_call("POST", "/sync/dms"), "sync")  # returned while DMs still block

    assert source.entered.wait(_TIMEOUT)
    status, _, running = _call("GET", f"/tasks/{task_id}")
    assert status == 200 and running["status"] == "running"
    source.release.set()
    done = _finished(task_id)

    assert done["status"] == "done"
    # No scanned posts yet: the threads touch nobody on the semáforo.
    assert done["result"] == {"hilos": 2}
    assert done["error"] is None and done["error_code"] is None
    with Session(engine) as s:  # the worker wrote with its own session
        assert len(s.exec(select(models.DmThread)).all()) == 2
    assert _activity(engine) == [("sync", "done", "2 hilos")]


def test_same_job_again_returns_the_running_one(
    use_source: Callable[[InstagramSource], None],
) -> None:
    source = GatedSource()
    use_source(source)
    first = _started(*_call("POST", "/sync/dms"), "sync")
    assert source.entered.wait(_TIMEOUT)
    again = _started(*_call("POST", "/sync/dms"), "sync")

    assert again == first
    source.release.set()
    assert _finished(first)["status"] == "done"
    assert source.dm_calls == 1  # one Instagram read, not two


def test_another_ig_job_while_one_runs_is_409_and_runs_nothing(
    engine: Engine, use_source: Callable[[InstagramSource], None]
) -> None:
    source = GatedSource()
    use_source(source)
    event_id = _event(engine)
    earlier = {t.id for t in registry.list()}  # finished jobs of other tests
    first = _started(*_call("POST", "/sync/dms"), "sync")
    assert source.entered.wait(_TIMEOUT)

    attempts = [
        ("POST", f"/events/{event_id}/refresh", None, None),
        ("POST", f"/events/{event_id}/rescan", None, None),
        ("POST", f"/events/{event_id}/enrich", None, None),
        ("POST", "/scan/posts", None, {"urls": [POST_A]}),
        ("POST", "/sync/dms", {"force": "true"}, None),  # same kind, other params
    ]
    for method, path, params, body in attempts:
        status, _, out = _call(method, path, params, body)
        assert status == 409, path
        assert out == {"detail": {"code": "conflict", "message": BUSY}}

    _, _, listed = _call("GET", "/tasks")
    assert [t["id"] for t in listed if t["id"] not in earlier] == [first]  # nothing queued
    source.release.set()
    assert _finished(first)["status"] == "done"
    assert source.dm_calls == 1
    with Session(engine) as s:  # the refused scan never ran
        assert s.exec(select(models.Post)).all() == []
    # Once it finished, the next one starts.
    assert _job_result("POST", "/scan/posts", "scan", body={"urls": [POST_A]})["status"] == "done"


# -- failures -----------------------------------------------------------------


def test_failed_job_stores_a_spanish_message_and_code(
    engine: Engine, use_source: Callable[[InstagramSource], None]
) -> None:
    done = _job_result(
        "POST", "/scan/posts", "scan", body={"urls": ["https://instagram.com/p/nope/"]}
    )
    assert done["status"] == "error"
    assert done["error"] == "No se encontró el post (borrado, privado o link inválido)."
    assert done["error_code"] == "post_not_found"
    assert done["result"] == {}
    assert _activity(engine) == [
        ("scan", "error", "No se encontró el post (borrado, privado o link inválido).")
    ]


def test_unexpected_crash_is_stored_and_frees_the_slot(
    use_source: Callable[[InstagramSource], None],
) -> None:
    use_source(CrashingSource())
    done = _job_result("POST", "/sync/dms", "sync")
    assert done["status"] == "error"
    assert done["error"] == "Error inesperado: RuntimeError: boom"
    assert done["error_code"] == "unknown"
    use_source(FakeInstagramSource())
    assert _job_result("POST", "/sync/dms", "sync")["status"] == "done"


def test_sync_surfaces_the_capped_warning(
    engine: Engine, use_source: Callable[[InstagramSource], None]
) -> None:
    with Session(engine) as s:  # a previous sync: this one is incremental
        AppStateRepository(s).set_dt(KEY_DMS_SYNCED, datetime(2026, 6, 1, tzinfo=UTC))
        s.commit()
    use_source(CappedSource())
    done = _job_result("POST", "/sync/dms", "sync")
    assert done["status"] == "done"
    assert done["warning"] == CAPPED_NOTE  # its own field (L15)
    assert done["result"] == {"hilos": 0, "aviso": CAPPED_NOTE}  # kept for the current UI
    assert _activity(engine) == [("sync", "done", f"0 hilos — aviso: {CAPPED_NOTE}")]


def test_unknown_task_is_404() -> None:
    status, _, body = _call("GET", "/tasks/nope")
    assert status == 404
    assert body == {
        "detail": {"code": "not_found", "message": "tarea no encontrada (terminó hace rato?)"}
    }


# -- previous behavior of every changed endpoint ------------------------------


def test_scan_posts_result_is_unchanged(
    engine: Engine, use_source: Callable[[InstagramSource], None]
) -> None:
    event_id = _event(engine)
    done = _job_result(
        "POST", "/scan/posts", "scan", body={"urls": [POST_A, POST_B], "event_id": event_id}
    )
    assert done["label"] == "Escaneando posts"
    assert done["result"] == {"posts": 2, "usuarios": 6, "nuevos": 4, "rojos nuevos": 4}
    assert (done["current"], done["total"]) == (1, 2)


def test_scan_posts_without_urls_or_range_is_still_422_and_starts_nothing(
    use_source: Callable[[InstagramSource], None],
) -> None:
    status, _, body = _call("POST", "/scan/posts", body={"event_id": None})
    assert status == 422
    assert body == {"detail": {"code": "bad_request", "message": "provide urls or from+to"}}
    _, _, listed = _call("GET", "/tasks")
    assert all(t["status"] != "running" for t in listed)


def test_refresh_result_is_unchanged(
    engine: Engine, use_source: Callable[[InstagramSource], None]
) -> None:
    event_id = _event(engine)
    _job_result(
        "POST", "/scan/posts", "scan", body={"urls": [POST_A, POST_B], "event_id": event_id}
    )
    done = _job_result("POST", f"/events/{event_id}/refresh", "refresh", params={"force": "true"})
    assert done["label"] == "Actualizando fiesta"
    assert done["result"] == {
        "posts": 2,
        "nuevos": 0,
        "respondieron": 1,
        "amarillos": 1,
        "hilos": 2,
    }


def test_enrich_result_is_unchanged(
    engine: Engine, use_source: Callable[[InstagramSource], None]
) -> None:
    event_id = _event(engine)
    _job_result(
        "POST", "/scan/posts", "scan", body={"urls": [POST_A, POST_B], "event_id": event_id}
    )
    _job_result("POST", "/sync/dms", "sync")
    done = _job_result("POST", f"/events/{event_id}/enrich", "enrich")
    assert done["label"] == "Enriqueciendo (relación + perfiles)"
    assert done["result"] == {
        "relaciones": 4,
        "perfiles": 4,
        "faltan": 0,
        "te siguen": "0/2 rojos",
    }


def test_rescan_is_now_a_tracked_job(
    engine: Engine, use_source: Callable[[InstagramSource], None]
) -> None:
    event_id = _event(engine)
    _job_result(
        "POST", "/scan/posts", "scan", body={"urls": [POST_A, POST_B], "event_id": event_id}
    )
    fresh = _job_result("POST", f"/events/{event_id}/rescan", "rescan")
    assert fresh["label"] == "Re-escaneando fiesta"
    # Both posts were scanned moments ago: skipped (RESCAN_SKIP_HOURS), no IG call.
    assert fresh["result"] == {"posts": 0, "usuarios": 0, "nuevos": 0, "salteados": 2}
    forced = _job_result("POST", f"/events/{event_id}/rescan", "rescan", params={"force": "true"})
    assert forced["result"] == {"posts": 2, "usuarios": 6, "nuevos": 0}


@pytest.mark.parametrize("action", ["rescan", "refresh", "enrich"])
def test_missing_event_is_still_404_and_starts_nothing(
    action: str, use_source: Callable[[InstagramSource], None]
) -> None:
    status, _, body = _call("POST", f"/events/999/{action}")
    assert status == 404
    assert body == {"detail": {"code": "not_found", "message": "fiesta"}}
    _, _, listed = _call("GET", "/tasks")
    assert all(t["status"] != "running" for t in listed)


def test_tasks_list_still_lists_jobs(use_source: Callable[[InstagramSource], None]) -> None:
    task_id = _started(*_call("POST", "/sync/dms"), "sync")
    _finished(task_id)
    status, _, listed = _call("GET", "/tasks")
    assert status == 200
    mine = next(t for t in listed if t["id"] == task_id)
    assert set(mine) == {
        "id",
        "kind",
        "label",
        "status",
        "current",
        "total",
        "message",
        "result",
        "warning",
        "error",
        "error_code",
        "started_at",
        "finished_at",
    }


# -- SSE ----------------------------------------------------------------------


def test_stream_endpoint_is_event_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    # Pretend the server is shutting down so the stream ends after its snapshot.
    monkeypatch.setattr(tasks_router, "streams_stopped", lambda: True)
    status, headers, body = _call("GET", "/tasks/stream")
    assert status == 200
    assert headers["content-type"].startswith("text/event-stream")
    assert headers["cache-control"] == "no-cache"
    assert body.startswith("retry: 3000\nevent: tasks\ndata: [")


def test_shutdown_signals_end_the_streams_then_reach_uvicorn() -> None:
    """uvicorn (and `--reload`, which stops the worker with Ctrl+C on Windows)
    waits for open responses: the signal must end the SSE streams first."""
    from app import main

    names = [n for n in ("SIGINT", "SIGTERM", "SIGBREAK") if hasattr(signal, n)]
    sigs = [getattr(signal, n) for n in names]
    originals = {s: signal.getsignal(s) for s in sigs}
    received: list[int] = []
    try:
        for s in sigs:
            signal.signal(s, lambda signum, frame: received.append(signum))
        main._stop_streams_on_exit_signals()
        for s in sigs:
            tasks_router._stopping.clear()
            handler = signal.getsignal(s)
            assert callable(handler)
            handler(s, None)
            assert tasks_router.streams_stopped(), names
        assert received == sigs  # uvicorn's own handler still runs, in order
    finally:
        for s, h in originals.items():
            signal.signal(s, h)
        tasks_router._stopping.clear()
