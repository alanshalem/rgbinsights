"""App startup/shutdown: SSE stop flag and the exit-signal chaining (L15)."""

from __future__ import annotations

import asyncio
import signal
import threading
from collections.abc import Iterator
from typing import Any

import pytest
from app import bootstrap, main
from app.api.routers import tasks as tasks_router

_SIGNALS = [getattr(signal, n) for n in ("SIGINT", "SIGTERM", "SIGBREAK") if hasattr(signal, n)]


@pytest.fixture
def restore_signals() -> Iterator[None]:
    originals = {s: signal.getsignal(s) for s in _SIGNALS}
    try:
        yield
    finally:
        for s, handler in originals.items():
            signal.signal(s, handler)
        tasks_router.reset_streams()


@pytest.mark.parametrize("previous", [signal.SIG_DFL, signal.SIG_IGN], ids=["default", "ignored"])
def test_default_or_ignored_handlers_are_left_alone(restore_signals: None, previous: Any) -> None:
    for s in _SIGNALS:
        signal.signal(s, previous)

    main._stop_streams_on_exit_signals()

    assert [signal.getsignal(s) for s in _SIGNALS] == [previous] * len(_SIGNALS)
    assert not tasks_router.streams_stopped()


def test_outside_the_main_thread_it_does_nothing(restore_signals: None) -> None:
    received: list[int] = []
    for s in _SIGNALS:
        signal.signal(s, lambda signum, frame: received.append(signum))
    before = [signal.getsignal(s) for s in _SIGNALS]
    errors: list[BaseException] = []

    def run() -> None:
        try:
            main._stop_streams_on_exit_signals()
        except BaseException as exc:  # noqa: BLE001 — the test reports it
            errors.append(exc)

    worker = threading.Thread(target=run)
    worker.start()
    worker.join(5)

    assert errors == []
    assert [signal.getsignal(s) for s in _SIGNALS] == before


def test_startup_clears_a_stop_left_by_an_earlier_shutdown(
    restore_signals: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    resumed: list[bool] = []
    monkeypatch.setattr(main, "create_db_and_tables", lambda _engine: None)
    monkeypatch.setattr(main, "_stop_streams_on_exit_signals", lambda: None)
    monkeypatch.setattr(bootstrap.campaign_sender, "resume_all", lambda: resumed.append(True))
    tasks_router.stop_streams()  # e.g. a uvicorn --reload in the same process

    async def scenario() -> tuple[bool, bool]:
        async with main.lifespan(main.app):
            during = tasks_router.streams_stopped()
        return during, tasks_router.streams_stopped()

    during, after = asyncio.run(scenario())

    assert during is False  # new SSE streams are not ended at once
    assert after is True  # shutdown still ends them
    assert resumed == [True]
