"""Background jobs for the long Instagram operations (S16).

Scan / rescan / sync DMs / refresh / enrich each start a job and return at once
(HTTP 202 + the job): the work runs in a daemon worker thread with its own unit
of work (DB session), reports progress on its Task, and leaves its result (or
its error) on it. GET /tasks/stream pushes every change to the UI (SSE); GET
/tasks is the polling fallback. Tasks are ephemeral (pruned shortly after they
finish), so no persistence — unlike campaigns, which have their own engine.

Every job talks to Instagram, so at most ONE runs at a time (S0): starting the
same kind with the same parameters while it runs returns that running job (a
double click, a second tab); anything else is refused with JobConflictError
(HTTP 409) — never queued, never run in parallel. Inside the job every
Instagram call still goes through IgGuard (one request at a time process-wide,
budget, human pacing, no retries) exactly as before. Daemon threads never keep
the process alive, so a shutdown or `uvicorn --reload` is not held by a job.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.application.dto import ScanBatchResult, StatusCounts
from app.application.ports import UnitOfWork, UnitOfWorkFactory
from app.domain.result import Err, ErrorCode, Result

logger = logging.getLogger(__name__)

_KEEP_FINISHED_SECONDS = 25.0

# A failed job's message is shown as is, so it is always Spanish: the use case's
# own message (every domain/adapter message is Spanish and the most specific),
# or this text for its code when it has none.
JOB_MESSAGE_BY_CODE: dict[ErrorCode, str] = {
    ErrorCode.POST_NOT_FOUND: "No se encontró el post (borrado, privado o link inválido).",
    ErrorCode.CHALLENGE_REQUIRED: "Instagram pide verificación: reconectá desde el chip IG.",
    ErrorCode.LOGIN_REQUIRED: "La sesión de Instagram se cerró: reconectá desde el chip IG.",
    ErrorCode.IP_BLOCKED: "Instagram bloqueó la conexión (IP), no la sesión.",
    ErrorCode.RATE_LIMITED: "Instagram pidió frenar: probá de nuevo más tarde.",
    ErrorCode.SEND_BLOCKED: "Instagram bloqueó el envío de mensajes.",
    ErrorCode.UNKNOWN: "Falló la operación con Instagram.",
}
_START_FAILED = "No se pudo iniciar la tarea en segundo plano."
_INTERRUPTED = "La tarea se interrumpió."


def job_error_message(err: Err) -> str:
    """The Spanish text a failed job shows for an expected failure."""
    return err.message or JOB_MESSAGE_BY_CODE.get(err.code, JOB_MESSAGE_BY_CODE[ErrorCode.UNKNOWN])


class JobFailed(Exception):
    """Raised by Task.unwrap: ends the job as an expected failure (not a crash)."""

    def __init__(self, err: Err) -> None:
        super().__init__(err.message)
        self.err = err


@dataclass(frozen=True, slots=True)
class TaskView:
    """A read-only copy of a job, as GET /tasks and the SSE stream show it."""

    id: str
    kind: str
    label: str
    status: str
    current: int
    total: int
    message: str
    result: dict[str, Any]
    warning: str | None
    error: str | None
    error_code: str | None
    started_at: datetime
    finished_at: datetime | None


@dataclass
class Task:
    """A running job. Only its own work changes it (through these methods); the
    registry hands everyone else TaskView copies."""

    id: str
    kind: str  # scan | rescan | sync | refresh | enrich
    label: str
    status: str = "running"  # running | done | error
    current: int = 0
    total: int = 0
    message: str = ""
    result: dict[str, Any] = field(default_factory=dict)
    warning: str | None = None  # Spanish: something the user should know (job still done)
    error: str | None = None  # Spanish, shown as is
    error_code: str | None = None  # ErrorCode value (e.g. challenge_required)
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None
    key: str = field(default="", repr=False)  # kind + parameters (duplicate detection)
    _owner: TaskRegistry | None = field(default=None, repr=False, compare=False)

    def progress(self, current: int, total: int | None = None, message: str = "") -> None:
        changes: dict[str, Any] = {"current": current}
        if total is not None:
            changes["total"] = total
        if message:
            changes["message"] = message
        self._set(changes)

    def fail(self, message: str, code: str = "unknown") -> None:
        """Mark the outcome as failed; the job ends as `error` when its work returns."""
        self._set({"error": message, "error_code": code})

    def set_result(self, result: dict[str, Any], *, warning: str | None = None) -> None:
        """The summary shown when the job is done ("2 posts · 4 nuevos"), plus
        an optional warning shown on its own line."""
        self._set({"result": result, "warning": warning})

    def unwrap[T](self, result: Result[T]) -> T:
        """The value of an Ok; an Err ends the job as failed with its Spanish
        message (the registry catches the JobFailed this raises)."""
        if isinstance(result, Err):
            raise JobFailed(result)
        return result.value

    def summary(self) -> str:
        """One line for the activity feed: the error, or the result and warning."""
        if self.error is not None:
            return self.error
        text = " · ".join(f"{v} {k}" for k, v in self.result.items()) or self.label
        return f"{text} — aviso: {self.warning}" if self.warning else text

    def view(self) -> TaskView:
        return TaskView(
            id=self.id,
            kind=self.kind,
            label=self.label,
            status=self.status,
            current=self.current,
            total=self.total,
            message=self.message,
            result=dict(self.result),
            warning=self.warning,
            error=self.error,
            error_code=self.error_code,
            started_at=self.started_at,
            finished_at=self.finished_at,
        )

    def _set(self, changes: dict[str, Any]) -> None:
        if self._owner is None:
            for name, value in changes.items():
                setattr(self, name, value)
        else:
            self._owner._apply(self, changes)


JobWork = Callable[[Task, UnitOfWork], None]


class JobConflictError(Exception):
    """Another Instagram job is running: refused instead of run in parallel."""

    def __init__(self, running_label: str) -> None:
        super().__init__(
            f"Ya hay una tarea con Instagram en curso («{running_label}»). "
            "Esperá a que termine y probá de nuevo."
        )


class TaskRegistry:
    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}
        self._lock = threading.Lock()
        self._version = 0  # bumped on every change; SSE streams wait on it
        self._waiters: set[tuple[asyncio.AbstractEventLoop, asyncio.Event]] = set()

    # -- jobs -------------------------------------------------------------------

    def start(
        self, kind: str, label: str, key: str, work: JobWork, new_uow: UnitOfWorkFactory
    ) -> TaskView:
        """Run `work` in a daemon worker thread; return the job at once (a view).

        Raises JobConflictError while another job runs, unless it is the same
        `key` (kind + parameters): then that running job is returned instead.
        """
        with self._lock:
            self._prune()
            running = next((t for t in self._tasks.values() if t.status == "running"), None)
            if running is not None:
                if running.key == key:
                    return running.view()
                raise JobConflictError(running.label)
            task = Task(id=uuid.uuid4().hex[:10], kind=kind, label=label, key=key, _owner=self)
            self._tasks[task.id] = task
            self._changed()
            view = task.view()
        thread = threading.Thread(
            target=self._run,
            args=(task, work, new_uow),
            name=f"job-{kind}-{task.id}",
            daemon=True,
        )
        try:
            thread.start()
        except RuntimeError:
            # Never leave a "running" job that blocks every later one.
            self._finish(task, _START_FAILED)
            raise
        return view

    def _run(self, task: Task, work: JobWork, new_uow: UnitOfWorkFactory) -> None:
        crash: str | None = _INTERRUPTED  # stays if the work ends by SystemExit & co.
        try:
            with new_uow() as uow:
                work(task, uow)
            crash = None
        except JobFailed as failed:
            task.fail(job_error_message(failed.err), failed.err.code.value)
            crash = None
        except Exception as exc:
            logger.exception("job %s (%s) failed", task.id, task.kind)
            crash = f"Error inesperado: {type(exc).__name__}: {exc}"
        finally:
            if crash is not None and task.error is None:
                task.fail(crash, ErrorCode.UNKNOWN.value)
            # The activity row first: a job seen as finished is already in the feed.
            status = "error" if task.error is not None else "done"
            log_activity(new_uow, task.kind, status, task.summary())
            self._finish(task, None)

    def _finish(self, task: Task, crash: str | None) -> None:
        with self._lock:
            if crash is not None and task.error is None:
                task.error, task.error_code = crash, ErrorCode.UNKNOWN.value
            task.status = "error" if task.error is not None else "done"
            task.finished_at = datetime.now(UTC)
            self._changed()

    def _apply(self, task: Task, changes: dict[str, Any]) -> None:
        with self._lock:
            for name, value in changes.items():
                setattr(task, name, value)
            self._changed()

    # -- reads ------------------------------------------------------------------

    def list(self) -> list[TaskView]:
        """Views of the current tasks, oldest first."""
        with self._lock:
            self._prune()
            return [t.view() for t in sorted(self._tasks.values(), key=lambda t: t.started_at)]

    def get(self, task_id: str) -> TaskView | None:
        with self._lock:
            task = self._tasks.get(task_id)
            return task.view() if task is not None else None

    @property
    def version(self) -> int:
        return self._version

    async def wait_for_change(self, version: int, timeout: float) -> int:
        """Wait, without blocking the event loop, until a change after `version`
        (pushed by the worker threads) or `timeout`; return the current version."""
        waiter = (asyncio.get_running_loop(), asyncio.Event())
        with self._lock:
            if self._version != version:
                return self._version
            self._waiters.add(waiter)
        try:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(waiter[1].wait(), timeout)
        finally:
            with self._lock:
                self._waiters.discard(waiter)
        return self._version

    def waiting(self) -> int:
        """How many streams are waiting for a change right now."""
        with self._lock:
            return len(self._waiters)

    def _changed(self) -> None:
        """Call with `_lock` held: bump the version and wake every SSE stream."""
        self._version += 1
        for loop, event in self._waiters:
            with contextlib.suppress(RuntimeError):  # that loop already closed
                loop.call_soon_threadsafe(event.set)

    def _prune(self) -> None:
        now = datetime.now(UTC)
        stale = [
            t.id
            for t in self._tasks.values()
            if t.finished_at is not None
            and (now - t.finished_at).total_seconds() > _KEEP_FINISHED_SECONDS
        ]
        for tid in stale:
            del self._tasks[tid]


def scan_summary(
    batch: ScanBatchResult, before: StatusCounts, after: StatusCounts
) -> dict[str, Any]:
    """The toast numbers of a scan/rescan: new reds = people this scan surfaced."""
    nuevos_rojos = max(0, after.red - before.red)
    return {
        "posts": len(batch.results),
        "usuarios": batch.total_users_found,
        "nuevos": batch.total_new_users,
        **({"rojos nuevos": nuevos_rojos} if nuevos_rojos else {}),
    }


def log_activity(new_uow: UnitOfWorkFactory, kind: str, status: str, message: str) -> None:
    """Persist one activity row (best-effort; never breaks the caller)."""
    try:
        with new_uow() as uow:
            uow.activity.add(kind, status, message)
            uow.commit()
    except Exception:  # noqa: BLE001 — logging must not break the operation
        logger.warning("could not write the activity row", exc_info=True)
