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
from app.application.ports import UnitOfWork
from app.application.tasks import (
    JOB_MESSAGE_BY_CODE,
    JobConflictError,
    Task,
    TaskRegistry,
    TaskView,
    job_error_message,
)
from app.domain.result import Err, ErrorCode

_TIMEOUT = 5.0


class _NoSession:
    """Unit-of-work factory stand-in: these jobs never touch the DB; activity
    rows are kept in memory (with the job's status when each was written)."""

    def __init__(self, registry: TaskRegistry | None = None) -> None:
        self.registry = registry
        self.activity: list[tuple[str, str, str]] = []
        self.status_when_logged: list[str | None] = []

    def __call__(self) -> Any:
        return _DummyUow(self)


class _DummyUow:
    def __init__(self, owner: _NoSession) -> None:
        self.owner = owner
        self.activity = self

    def __enter__(self) -> _DummyUow:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def add(self, kind: str, status: str, message: str) -> None:
        self.owner.activity.append((kind, status, message))
        reg = self.owner.registry
        if reg is not None:
            listed = reg.list()
            self.owner.status_when_logged.append(listed[-1].status if listed else None)

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


def _wait_finished(registry: TaskRegistry, task_id: str) -> TaskView:
    deadline = time.monotonic() + _TIMEOUT
    while True:
        task = registry.get(task_id)
        assert task is not None
        if task.status != "running":
            return task
        assert time.monotonic() < deadline, "job never finished"
        time.sleep(0.01)


def _gated(gate: threading.Event, seen: dict[str, Any]) -> Callable[[Task, UnitOfWork], None]:
    def work(task: Task, _uow: UnitOfWork) -> None:
        seen["thread"] = threading.current_thread()
        seen["task"] = task
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
    def work(task: Task, _uow: UnitOfWork) -> None:
        task.fail("Instagram pidió frenar.", "rate_limited")

    task = reg.start("sync", "Sincronizando DMs", "k", work, _NoSession())
    done = _wait_finished(reg, task.id)
    assert done.status == "error"
    assert done.error == "Instagram pidió frenar."
    assert done.error_code == "rate_limited"


def test_unexpected_exception_is_stored_in_spanish_and_frees_the_slot(reg: TaskRegistry) -> None:
    def work(_task: Task, _uow: UnitOfWork) -> None:
        raise RuntimeError("boom")

    task = reg.start("sync", "Sincronizando DMs", "k", work, _NoSession())
    done = _wait_finished(reg, task.id)
    assert done.status == "error"
    assert done.error == "Error inesperado: RuntimeError: boom"
    assert done.error_code == "unknown"
    nxt = reg.start("sync", "Sincronizando DMs", "k", lambda t, s: None, _NoSession())
    assert _wait_finished(reg, nxt.id).status == "done"


def test_reads_are_read_only_views_and_only_the_job_changes_the_task(reg: TaskRegistry) -> None:
    gate, seen = threading.Event(), dict[str, Any]()
    task = reg.start("sync", "Sincronizando DMs", "k", _gated(gate, seen), _NoSession())
    snap = reg.list()[0]
    view = reg.get(task.id)
    assert isinstance(snap, TaskView) and isinstance(view, TaskView)
    assert not hasattr(view, "progress")  # a view cannot write the job back
    with pytest.raises(AttributeError):
        view.current = 5  # type: ignore[misc]
    _wait_for(lambda: "task" in seen)
    seen["task"].progress(3, 10, "hilo 3")  # the job itself reports progress
    assert snap.current == 0  # an earlier view never changes under a reader
    assert reg.get(task.id).current == 3  # type: ignore[union-attr]
    gate.set()


def _wait_for(condition: Callable[[], bool]) -> None:
    deadline = time.monotonic() + _TIMEOUT
    while not condition():
        assert time.monotonic() < deadline, "condition never met"
        time.sleep(0.01)


# -- change notification + SSE ------------------------------------------------


def test_progress_wakes_a_waiter_at_once(reg: TaskRegistry) -> None:
    gate, seen = threading.Event(), dict[str, Any]()
    reg.start("sync", "Sincronizando DMs", "k", _gated(gate, seen), _NoSession())
    _wait_for(lambda: "task" in seen)

    async def scenario() -> float:
        version = reg.version
        live = seen["task"]
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

    def work(task: Task, _uow: UnitOfWork) -> None:
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


# -- L15: registry edge cases ---------------------------------------------------


def test_thread_start_failure_is_an_error_and_frees_the_slot(
    reg: TaskRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(_self: threading.Thread) -> None:
        raise RuntimeError("can't start new thread")

    with monkeypatch.context() as patch:
        patch.setattr(threading.Thread, "start", refuse)
        with pytest.raises(RuntimeError):
            reg.start("sync", "Sincronizando DMs", "k", lambda t, u: None, _NoSession())

    (failed,) = reg.list()
    assert failed.status == "error"
    assert failed.error == "No se pudo iniciar la tarea en segundo plano."
    assert failed.error_code == "unknown"
    nxt = reg.start("sync", "Sincronizando DMs", "k", lambda t, u: None, _NoSession())
    assert _wait_finished(reg, nxt.id).status == "done"


# The SystemExit still ends the worker thread (it is not swallowed): pytest notes it.
@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_system_exit_inside_a_job_ends_it_as_interrupted(reg: TaskRegistry) -> None:
    uows = _NoSession()

    def work(_task: Task, _uow: UnitOfWork) -> None:
        raise SystemExit(1)

    task = reg.start("sync", "Sincronizando DMs", "k", work, uows)
    done = _wait_finished(reg, task.id)
    for worker in threading.enumerate():  # let the SystemExit end its thread here
        if worker.name == f"job-sync-{task.id}":
            worker.join(_TIMEOUT)
    assert done.status == "error"
    assert done.error == "La tarea se interrumpió."
    assert done.error_code == "unknown"
    assert uows.activity == [("sync", "error", "La tarea se interrumpió.")]
    nxt = reg.start("sync", "Sincronizando DMs", "k", lambda t, u: None, _NoSession())
    assert _wait_finished(reg, nxt.id).status == "done"


def test_fifty_concurrent_starts_run_exactly_one_job(reg: TaskRegistry) -> None:
    gate, seen = threading.Event(), dict[str, Any]()
    barrier = threading.Barrier(50)
    started: list[tuple[str, str]] = []  # (key, task id)
    refused: list[str] = []
    lock = threading.Lock()

    def starter(i: int) -> None:
        key = "same" if i % 2 else f"other-{i}"
        barrier.wait(_TIMEOUT)
        try:
            view = reg.start("sync", "Sincronizando DMs", key, _gated(gate, seen), _NoSession())
        except JobConflictError:
            with lock:
                refused.append(key)
            return
        with lock:
            started.append((key, view.id))

    threads = [threading.Thread(target=starter, args=(i,)) for i in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(_TIMEOUT)

    (only,) = reg.list()
    assert only.status == "running"
    assert len(started) + len(refused) == 50
    assert {task_id for _, task_id in started} == {only.id}
    winner_keys = {key for key, _ in started}
    assert len(winner_keys) == 1  # only callers with the running job's key get it back
    assert winner_keys.isdisjoint(refused)
    gate.set()
    assert _wait_finished(reg, only.id).status == "done"


def test_fifty_stream_clients_all_see_the_final_state_and_leave_no_waiters(
    reg: TaskRegistry,
) -> None:
    gate = threading.Event()

    def work(task: Task, _uow: UnitOfWork) -> None:
        assert gate.wait(_TIMEOUT)
        task.set_result({"hilos": 1})

    task = reg.start("sync", "Sincronizando DMs", "k", work, _NoSession())

    async def scenario() -> list[str]:
        connected = 0
        all_connected = asyncio.Event()

        async def client() -> str:
            nonlocal connected
            gen = task_events(registry=reg, heartbeat=30.0, stopped=lambda: False)
            try:
                first = _parse(await _next(gen))
                assert first is not None and first[0]["status"] == "running"
                connected += 1
                if connected == 50:
                    all_connected.set()
                while True:
                    snap = _parse(await _next(gen))
                    if snap and snap[0]["status"] != "running":
                        return str(snap[0]["status"])
            finally:
                await gen.aclose()

        clients = [asyncio.create_task(client()) for _ in range(50)]
        await asyncio.wait_for(all_connected.wait(), _TIMEOUT)
        gate.set()
        return await asyncio.gather(*clients)

    assert asyncio.run(scenario()) == ["done"] * 50
    assert reg.waiting() == 0
    assert _wait_finished(reg, task.id).result == {"hilos": 1}


def test_activity_row_is_written_before_the_job_shows_as_finished(reg: TaskRegistry) -> None:
    uows = _NoSession(registry=reg)

    def work(task: Task, _uow: UnitOfWork) -> None:
        task.set_result({"hilos": 2})

    task = reg.start("sync", "Sincronizando DMs", "k", work, uows)
    assert _wait_finished(reg, task.id).status == "done"
    assert uows.activity == [("sync", "done", "2 hilos")]
    assert uows.status_when_logged == ["running"]  # finished only after the row exists


def test_a_warning_is_its_own_field_and_reads_well_in_the_activity(reg: TaskRegistry) -> None:
    uows = _NoSession()

    def work(task: Task, _uow: UnitOfWork) -> None:
        task.set_result({"hilos": 0}, warning="se llegó al tope de chats")

    task = reg.start("sync", "Sincronizando DMs", "k", work, uows)
    done = _wait_finished(reg, task.id)
    assert done.result == {"hilos": 0}
    assert done.warning == "se llegó al tope de chats"
    assert uows.activity == [("sync", "done", "0 hilos — aviso: se llegó al tope de chats")]


def test_unwrap_ends_the_job_with_the_spanish_message(reg: TaskRegistry) -> None:
    ran_after: list[bool] = []
    uows = _NoSession()

    def work(task: Task, _uow: UnitOfWork) -> None:
        task.unwrap(Err(ErrorCode.RATE_LIMITED))
        ran_after.append(True)

    task = reg.start("sync", "Sincronizando DMs", "k", work, uows)
    done = _wait_finished(reg, task.id)
    assert done.status == "error"
    assert done.error == "Instagram pidió frenar: probá de nuevo más tarde."
    assert done.error_code == "rate_limited"
    assert ran_after == []
    assert uows.activity == [("sync", "error", "Instagram pidió frenar: probá de nuevo más tarde.")]


def test_every_error_code_has_a_spanish_job_message() -> None:
    assert set(JOB_MESSAGE_BY_CODE) == set(ErrorCode)
    for code in ErrorCode:
        assert job_error_message(Err(code)) == JOB_MESSAGE_BY_CODE[code]
    detailed = "La sesión venció o el sessionid es inválido. Pegá un sessionid nuevo."
    assert job_error_message(Err(ErrorCode.LOGIN_REQUIRED, detailed)) == detailed
