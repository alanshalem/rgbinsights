"""In-memory task registry for long operations (scan/sync/refresh/enrich).

Each long endpoint runs inside `track(...)`, updating a Task's progress while it
works. The frontend polls GET /tasks to show a bottom-right toast with live
progress and the final result. Tasks are ephemeral (pruned shortly after they
finish), so no persistence — unlike campaigns, which have their own engine.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

_KEEP_FINISHED_SECONDS = 25.0


@dataclass
class Task:
    id: str
    kind: str  # scan | sync | refresh | enrich
    label: str
    status: str = "running"  # running | done | error
    current: int = 0
    total: int = 0
    message: str = ""
    result: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None

    def progress(self, current: int, total: int | None = None, message: str = "") -> None:
        self.current = current
        if total is not None:
            self.total = total
        if message:
            self.message = message

    def fail(self, message: str) -> None:
        self.error = message


class _Registry:
    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}
        self._lock = threading.Lock()

    @contextmanager
    def track(self, kind: str, label: str) -> Iterator[Task]:
        task = Task(id=uuid.uuid4().hex[:10], kind=kind, label=label)
        with self._lock:
            self._prune()
            self._tasks[task.id] = task
        try:
            yield task
        except Exception as exc:
            task.status = "error"
            if task.error is None:
                task.error = str(exc)
            raise
        else:
            if task.status == "running":
                task.status = "done"
        finally:
            task.finished_at = datetime.now(UTC)

    def list(self) -> list[Task]:
        with self._lock:
            self._prune()
            return sorted(self._tasks.values(), key=lambda t: t.started_at)

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


registry = _Registry()
