"""Background job registry + the SSE stream that pushes its changes (S16)."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from collections.abc import AsyncIterator, Callable, Iterator
from typing import Any

import pytest
from app.api.routers.tasks import task_events
from app.application.tasks import JobConflictError, Task, TaskRegistry
from sqlmodel import Session

_TIMEOUT = 5.0


class _NoSession:
    """Session factory stand-in: these jobs never touch the DB."""

    def __call__(self) -> Session:
        return _DummySession()  # type: ignore[return-value]


class _DummySession:
    def __enter__(self) -> _DummySession:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def add(self, _row: object) -> None:
        return None

    def commit(self) -> None:
        return None


@pytest.fixture
def reg() -> Iterator[TaskRegistry]:
    registry = TaskRegistry()
    yield registry
    _wait_idle(registry)


def _wait_idle(registry: TaskRegistry) -> None:
    deadline = time.monotonic() + _TIMEOUT
    while any(t.status == "running" for t in registry.list()):
        assert time.monotonic() < deadline, "a job never finished"
        time.sleep(0.01)


def _wait_finished(registry: TaskRegistry, task_id: str) -> Task:
    deadline = time.monotonic() + _TIMEOUT
    while True:
        task = registry.get(task_id)
        assert task is not None
        if task.status != "running":
            return task
        assert time.monotonic() < deadline, "job never finished"
        time.sleep(0.01)


def _gated(gate: threading.Event, seen: dict[str, Any]) -> Callable[[Task, Session], None]:
    def work(task: Task, _session: Session) -> None:
        seen["thread"] = threading.current_thread()
        assert gate.wait(_TIMEOUT)
        task.set_result({"hilos": 2})

    return work


def test_start_returns_at_once_and_runs_in_a_daemon_worker(reg: TaskRegistry) -> None:
    gate, seen = threading.Event(), dict[str, Any]()
    task = reg.start("sync", "Sincronizando DMs", "sync:{}", _gated(gate, seen), _NoSession())

    assert task.status == "running"  # returned while the work is still blocked
    assert reg.get(task.id) is not None and reg.get(task.id).status == "running"  # type: ignore[union-attr]
    gate.set()
    done = _wait_finished(reg, task.id)

    assert done.status == "done"
    assert done.result == {"hilos": 2}
    assert done.error is None and done.error_code is None
    assert done.finished_at is not None
    worker = seen["thread"]
    assert worker is not threading.current_thread()
    assert worker.daemon  # never keeps the process alive on shutdown/reload


def test_same_kind_and_params_returns_the_running_job(reg: TaskRegistry) -> None:
    gate, seen = threading.Event(), dict[str, Any]()
    first = reg.start("sync", "Sincronizando DMs", "sync:{}", _gated(gate, seen), _NoSession())
    again = reg.start("sync", "Sincronizando DMs", "sync:{}", _gated(gate, seen), _NoSession())

    assert again.id == first.id
    assert [t.id for t in reg.list()] == [first.id]  # nothing queued
    gate.set()


def test_another_job_while_one_runs_is_refused(reg: TaskRegistry) -> None:
    gate, seen = threading.Event(), dict[str, Any]()
    first = reg.start("sync", "Sincronizando DMs", "sync:{}", _gated(gate, seen), _NoSession())
    ran: list[str] = []

    with pytest.raises(JobConflictError) as exc:
        reg.start("scan", "Escaneando posts", "scan:{}", lambda t, s: ran.append("x"), _NoSession())
    assert str(exc.value) == (
        "Ya hay una tarea con Instagram en curso («Sincronizando DMs»). "
        "Esperá a que termine y probá de nuevo."
    )
    with pytest.raises(JobConflictError):  # same kind, other params: also refused
        reg.start(
            "sync", "Sincronizando DMs", 'sync:{"force":true}', _gated(gate, seen), _NoSession()
        )

    gate.set()
    _wait_finished(reg, first.id)
    assert ran == []
    assert [t.id for t in reg.list()] == [first.id]
    # Once it finished, the next job starts normally.
    nxt = reg.start("scan", "Escaneando posts", "scan:{}", lambda t, s: None, _NoSession())
    assert _wait_finished(reg, nxt.id).status == "done"


def test_failure_is_stored_with_its_message_and_code(reg: TaskRegistry) -> None:
    def work(task: Task, _session: Session) -> None:
        task.fail("Instagram pidió frenar.", "rate_limited")

    task = reg.start("sync", "Sincronizando DMs", "k", work, _NoSession())
    done = _wait_finished(reg, task.id)
    assert done.status == "error"
    assert done.error == "Instagram pidió frenar."
    assert done.error_code == "rate_limited"


def test_unexpected_exception_is_stored_in_spanish_and_frees_the_slot(reg: TaskRegistry) -> None:
    def work(_task: Task, _session: Session) -> None:
        raise RuntimeError("boom")

    task = reg.start("sync", "Sincronizando DMs", "k", work, _NoSession())
    done = _wait_finished(reg, task.id)
    assert done.status == "error"
    assert done.error == "Error inesperado: RuntimeError: boom"
    assert done.error_code == "unknown"
    nxt = reg.start("sync", "Sincronizando DMs", "k", lambda t, s: None, _NoSession())
    assert _wait_finished(reg, nxt.id).status == "done"


def test_list_returns_snapshots_not_live_objects(reg: TaskRegistry) -> None:
    gate, seen = threading.Event(), dict[str, Any]()
    task = reg.start("sync", "Sincronizando DMs", "k", _gated(gate, seen), _NoSession())
    snap = reg.list()[0]
    live = reg.get(task.id)
    assert live is not None
    live.progress(3, 10, "hilo 3")
    assert snap.current == 0  # an earlier snapshot never changes under a reader
    assert reg.get(task.id).current == 3  # type: ignore[union-attr]
    gate.set()


# -- change notification + SSE ------------------------------------------------


def test_progress_wakes_a_waiter_at_once(reg: TaskRegistry) -> None:
    gate, seen = threading.Event(), dict[str, Any]()
    task = reg.start("sync", "Sincronizando DMs", "k", _gated(gate, seen), _NoSession())

    async def scenario() -> float:
        version = reg.version
        live = reg.get(task.id)
        assert live is not None
        loop = asyncio.get_running_loop()
        loop.call_later(0.05, lambda: threading.Thread(target=live.progress, args=(1, 4)).start())
        started = time.monotonic()
        new = await reg.wait_for_change(version, timeout=_TIMEOUT)
        assert new != version
        return time.monotonic() - started

    assert asyncio.run(scenario()) < 1.0  # pushed, not discovered by a slow poll
    gate.set()


def _parse(chunk: str) -> list[dict[str, Any]] | None:
    """The `tasks` event's JSON list, or None for a heartbeat/comment chunk."""
    data = [line[len("data: ") :] for line in chunk.splitlines() if line.startswith("data: ")]
    if not data:
        return None
    assert "event: tasks" in chunk.splitlines()
    parsed: list[dict[str, Any]] = json.loads("\n".join(data))
    return parsed


async def _next(gen: AsyncIterator[str]) -> str:
    return await asyncio.wait_for(anext(gen), _TIMEOUT)


def test_stream_pushes_snapshot_progress_and_completion(reg: TaskRegistry) -> None:
    gate = threading.Event()
    progressed = threading.Event()

    def work(task: Task, _session: Session) -> None:
        assert progressed.wait(_TIMEOUT)
        task.progress(1, 3, "hilo 1")
        assert gate.wait(_TIMEOUT)
        task.set_result({"hilos": 3})

    task = reg.start("sync", "Sincronizando DMs", "k", work, _NoSession())

    async def scenario() -> list[list[dict[str, Any]]]:
        gen = task_events(registry=reg, heartbeat=30.0, stopped=lambda: False)
        first = await _next(gen)
        assert first.startswith("retry: 3000\n")
        seen = [_parse(first)]
        progressed.set()
        seen.append(_parse(await _next(gen)))
        gate.set()
        while True:
            snap = _parse(await _next(gen))
            if snap and snap[0]["status"] != "running":
                seen.append(snap)
                break
        await gen.aclose()
        return [s for s in seen if s is not None]

    snapshot, progress, final = asyncio.run(scenario())
    assert snapshot[0]["id"] == task.id and snapshot[0]["status"] == "running"
    assert (progress[0]["current"], progress[0]["total"], progress[0]["message"]) == (
        1,
        3,
        "hilo 1",
    )
    assert final[0]["status"] == "done"
    assert final[0]["result"] == {"hilos": 3}
    assert final[0]["error"] is None and final[0]["error_code"] is None


def test_stream_sends_a_heartbeat_when_idle(reg: TaskRegistry) -> None:
    async def scenario() -> str:
        gen = task_events(registry=reg, heartbeat=0.1, stopped=lambda: False)
        await _next(gen)  # the initial snapshot
        beat = await _next(gen)
        await gen.aclose()
        return beat

    assert asyncio.run(scenario()) == ": ping\n\n"


def test_stream_ends_when_the_server_stops(reg: TaskRegistry) -> None:
    stop = threading.Event()

    async def scenario() -> list[str]:
        chunks: list[str] = []
        loop = asyncio.get_running_loop()
        loop.call_later(0.1, stop.set)
        started = time.monotonic()
        async for chunk in task_events(registry=reg, heartbeat=30.0, stopped=stop.is_set):
            chunks.append(chunk)
        assert time.monotonic() - started < 2.0  # never holds uvicorn's shutdown/reload
        return chunks

    chunks = asyncio.run(scenario())
    assert len(chunks) == 1 and _parse(chunks[0]) == []
