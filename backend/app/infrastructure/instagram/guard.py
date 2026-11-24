"""IgGuard: the single choke point between this app and Instagram (S2, S4, S5, S7).

- One Instagram operation at a time, process-wide (re-entrant lock, bounded wait).
- Login circuit breaker: after a failed login, wait 15 min -> 1 h -> 6 h before
  any new attempt; reset by a successful login.
- Cooldown: Instagram answering 429 / "please wait" / feedback_required stops
  every request for `ig_throttle_cooldown_minutes`.
- Real per-hour/per-day budget and human pacing for EVERY HTTP request.

`install()` wraps the request method of the client's requests sessions, the
one place all instagrapi traffic (private API, public/GraphQL, every page of a
paginated read) goes through, so nothing is counted or paced per call site.

State persists to a small JSON file rather than the DB on purpose: the guard
runs inside use cases' Instagram calls and must never depend on (or wait for)
their SQLite transactions.
"""

from __future__ import annotations

import contextlib
import functools
import hashlib
import json
import logging
import os
import random
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.infrastructure.config.settings import Settings
from app.infrastructure.instagram.errors import (
    ChallengeRequiredError,
    IgBusyError,
    InstagramError,
    IpBlockedError,
    LoginRequiredError,
    RateLimitedError,
)
from app.infrastructure.instagram.throttle import (
    HumanPacer,
    RequestBudget,
    format_local,
    non_negative_int,
)

logger = logging.getLogger(__name__)

# Escalating wait after consecutive failed logins (the last step repeats).
BREAKER_STEPS = (timedelta(minutes=15), timedelta(hours=1), timedelta(hours=6))

# Response-body markers of Instagram asking us to slow down (on 4xx responses).
_THROTTLE_MARKERS = (
    "please wait a few minutes",
    "feedback_required",
    "rate_limit_error",
    "sentry_block",
)

_BREAKER_KINDS: dict[str, type[InstagramError]] = {
    "ip": IpBlockedError,
    "challenge": ChallengeRequiredError,
    "login": LoginRequiredError,
}
_BREAKER_ERRORS = (IpBlockedError, ChallengeRequiredError, LoginRequiredError)
_GUARDED_ATTR = "_rgb_guarded"
# requests follows up to 30 redirects by default, each one a real request to
# Instagram. A legit flow needs one or two; a longer chain is a loop.
_MAX_REDIRECTS = 3


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class GuardSnapshot:
    """What /ig/status reports — read from memory, never from Instagram."""

    blocked_until: datetime | None  # no Instagram request before this (breaker/cooldown)
    breaker_open: bool  # a failed login is being waited out
    last_error: str | None
    last_ok_at: datetime | None


@dataclass
class _State:
    breaker_failures: int = 0
    breaker_until: datetime | None = None
    breaker_kind: str = ""
    breaker_error: str | None = None
    cooldown_until: datetime | None = None
    cooldown_reason: str | None = None
    last_error: str | None = None  # the most recent failure, for /ig/status
    last_ok_at: datetime | None = None
    # sha256 of the sessionid tried by the login that opened the breaker (never
    # the raw cookie): pasting that same value again is not a fresh credential.
    breaker_sessionid_hash: str | None = None


class IgGuard:
    def __init__(
        self,
        settings: Settings,
        *,
        clock: Callable[[], datetime] = _utcnow,
        sleep: Callable[[float], None] = time.sleep,
        rng: random.Random | None = None,
    ) -> None:
        self._settings = settings
        self._tz = settings.local_tz()
        self._clock = clock
        self._sleep = sleep
        self._path = Path(settings.ig_guard_file)
        self._lock = threading.RLock()  # one Instagram operation at a time
        self._state_lock = threading.Lock()  # guards _state/_budget for status readers
        self._pacer = HumanPacer(
            settings.scan_min_delay_seconds,
            settings.scan_max_delay_seconds,
            rest_every=settings.ig_rest_every_requests,
            rest_min=settings.ig_rest_min_seconds,
            rest_max=settings.ig_rest_max_seconds,
            rng=rng,
        )
        self._budget = RequestBudget(
            settings.ig_max_requests_per_hour, settings.ig_max_requests_per_day
        )
        self._state = _State()
        self._load()
        # Per-operation bookkeeping, touched only by the thread holding _lock.
        self._depth = 0
        self._attempts = 0
        self._succeeded = False
        self._stop: RateLimitedError | None = None
        self._sessionid_hash: str | None = None  # sessionid tried by this operation

    # -- operations ----------------------------------------------------------

    @contextlib.contextmanager
    def operation(self, *, fresh_sessionid: str | None = None) -> Iterator[None]:
        """Run one Instagram operation exclusively.

        Nested use (adapter -> login -> request) re-enters the same lock; only
        the outermost level checks the rails and records the outcome. With
        `fresh_sessionid` (the user pasted a sessionid) an open *login* breaker
        is skipped once, but only if it is not the sessionid whose login opened
        it; an IP-block breaker and the cooldown never are.
        """
        if not self._lock.acquire(timeout=self._settings.ig_lock_wait_seconds):
            raise IgBusyError(
                "Instagram está ocupado con otra operación (campaña o escaneo). "
                "Probá de nuevo en unos minutos."
            )
        self._depth += 1
        outer = self._depth == 1
        try:
            if outer:
                self._attempts, self._succeeded, self._stop = 0, False, None
                self._sessionid_hash = None
                if fresh_sessionid is not None:
                    self.note_sessionid(fresh_sessionid)
                self._ensure_open(fresh=fresh_sessionid is not None)
            try:
                yield
            except Exception as exc:
                if outer:
                    self._fail(exc)
                raise
            if outer and self._succeeded:
                self._ok()
        finally:
            self._depth -= 1
            self._lock.release()

    def _fail(self, exc: Exception) -> None:
        """Outcome of a failed outermost operation (re-raised by the caller)."""
        stop, self._stop = self._stop, None
        if stop is not None and exc is not stop:
            # instagrapi swallowed our stop and reported a misleading fallback
            # error (e.g. "not found"); the real cause wins.
            raise stop from exc
        if self._attempts and isinstance(exc, _BREAKER_ERRORS):
            self._trip_breaker(exc)

    def note_sessionid(self, sessionid: str) -> None:
        """The current operation logs in with this sessionid (kept as a hash)."""
        self._sessionid_hash = _sessionid_hash(sessionid)

    def _ensure_open(self, *, fresh: bool) -> None:
        now = self._clock()
        with self._state_lock:
            st = self._state
            cooldown, reason = st.cooldown_until, st.cooldown_reason
            breaker, kind, breaker_error = st.breaker_until, st.breaker_kind, st.breaker_error
            failed_hash = st.breaker_sessionid_hash
        if cooldown is not None and now < cooldown:
            raise self._cooldown_error(cooldown, reason)
        bypass = fresh and kind != "ip" and self._sessionid_hash != failed_hash
        if breaker is not None and now < breaker and not bypass:
            error_type = _BREAKER_KINDS.get(kind, LoginRequiredError)
            hint = "" if kind == "ip" else " o pegá un sessionid nuevo"
            raise error_type(
                f"{breaker_error or 'El último inicio de sesión falló.'} — Para no insistir con "
                f"Instagram, no se reintenta hasta las {self._fmt(breaker)} (hora AR){hint}."
            )

    def login_ok(self) -> None:
        """A login worked: close the breaker and reset its escalation."""
        self._update(
            breaker_failures=0,
            breaker_until=None,
            breaker_kind="",
            breaker_error=None,
            breaker_sessionid_hash=None,
            last_error=None,
            last_ok_at=self._clock(),
        )

    def _ok(self) -> None:
        """A successful operation: Instagram works again, so a stale error goes —
        unless a cooldown or the breaker is still running (its reason stays)."""
        now = self._clock()
        with self._state_lock:
            st = self._state
            blocked = any(t is not None and now < t for t in (st.cooldown_until, st.breaker_until))
        if blocked:
            self._update(last_ok_at=now)
        else:
            self._update(last_ok_at=now, last_error=None)

    def _trip_breaker(self, exc: InstagramError) -> None:
        with self._state_lock:
            failures = self._state.breaker_failures + 1
        until = self._clock() + BREAKER_STEPS[min(failures, len(BREAKER_STEPS)) - 1]
        kind = next(k for k, t in _BREAKER_KINDS.items() if isinstance(exc, t))
        logger.warning("IG login failed (%d in a row) — breaker open until %s", failures, until)
        self._update(
            breaker_failures=failures,
            breaker_until=until,
            breaker_kind=kind,
            breaker_error=str(exc),
            breaker_sessionid_hash=self._sessionid_hash,
            last_error=str(exc),
        )

    # -- per-request rails ---------------------------------------------------

    def install(self, client: Any) -> None:
        """Route every HTTP request of an instagrapi client through the guard.

        Wraps `Session.send`, which requests calls once per request AND once per
        redirect hop, so every hop is counted, paced and cooldown-checked.
        """
        client.delay_range = None  # pacing happens here, once, for every request
        for name in ("private", "public", "graphql"):
            session = getattr(client, name, None)
            send = getattr(session, "send", None)
            if send is None or getattr(send, _GUARDED_ATTR, False):
                continue
            session.max_redirects = _MAX_REDIRECTS  # type: ignore[union-attr]
            session.send = self._guarded(send)  # type: ignore[union-attr]

    def _guarded(self, send: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(send)
        def guarded_send(request: Any, *args: Any, **kwargs: Any) -> Any:
            with self.operation():
                self._before_request()
                response = send(request, *args, **kwargs)
                self._after_response(response)
                return response

        setattr(guarded_send, _GUARDED_ATTR, True)
        return guarded_send

    def _before_request(self) -> None:
        now = self._clock()
        with self._state_lock:
            cooldown, reason = self._state.cooldown_until, self._state.cooldown_reason
            if cooldown is not None and now < cooldown:
                raise self._remember_stop(self._cooldown_error(cooldown, reason))
            try:
                self._budget.spend(now.astimezone(self._tz))
            except RateLimitedError as exc:
                raise self._remember_stop(exc) from None
            finally:
                self._save()
        self._attempts += 1
        self._sleep(self._pacer.next_delay())

    def _after_response(self, response: Any) -> None:
        status = int(getattr(response, "status_code", 0) or 0)
        if status < 400:
            self._succeeded = True
            return
        try:
            body = str(response.text).lower()
        except Exception:  # noqa: BLE001 — an unreadable body just isn't a throttle marker
            body = ""
        marker = next((m for m in _THROTTLE_MARKERS if m in body), None)
        if status == 429 or marker is not None:
            reason = f"Instagram pidió frenar ({marker or 'HTTP 429'})"
            until = self._clock() + timedelta(minutes=self._settings.ig_throttle_cooldown_minutes)
            logger.warning("%s — cooldown until %s", reason, until)
            self._update(cooldown_until=until, cooldown_reason=reason, last_error=reason)

    def _remember_stop(self, exc: RateLimitedError) -> RateLimitedError:
        self._stop = exc
        return exc

    def _cooldown_error(self, until: datetime, reason: str | None) -> RateLimitedError:
        return RateLimitedError(
            f"{reason or 'Instagram pidió frenar'}. Pausa de seguridad: ningún pedido a "
            f"Instagram hasta las {self._fmt(until)} (hora AR)."
        )

    # -- status --------------------------------------------------------------

    def snapshot(self) -> GuardSnapshot:
        now = self._clock()
        with self._state_lock:
            st = self._state
            active = [t for t in (st.breaker_until, st.cooldown_until) if t and now < t]
            return GuardSnapshot(
                blocked_until=max(active) if active else None,
                breaker_open=st.breaker_until is not None and now < st.breaker_until,
                last_error=st.last_error,
                last_ok_at=st.last_ok_at,
            )

    # -- persistence ---------------------------------------------------------

    def _fmt(self, when: datetime) -> str:
        return format_local(when.astimezone(self._tz))

    def _update(self, **changes: Any) -> None:
        with self._state_lock:
            for key, value in changes.items():
                setattr(self._state, key, value)
            self._save()

    def _load(self) -> None:
        """Restore the saved state. Any unreadable or malformed content (wrong
        JSON shape or field types) falls back to a clean state: a bad file must
        never take the guard — and with it /ig/status and every IG call — down."""
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("not a JSON object")
            budget = data.get("budget", {})
            if not isinstance(budget, dict):
                raise ValueError("budget is not an object")
            kind = data.get("breaker_kind", "")
            if kind not in ("", *_BREAKER_KINDS):
                raise ValueError(f"unknown breaker kind {kind!r}")
            state = _State(
                breaker_failures=non_negative_int(data.get("breaker_failures", 0)),
                breaker_until=_parse_dt(data.get("breaker_until")),
                breaker_kind=kind,
                breaker_error=_opt_text(data.get("breaker_error")),
                cooldown_until=_parse_dt(data.get("cooldown_until")),
                cooldown_reason=_opt_text(data.get("cooldown_reason")),
                last_error=_opt_text(data.get("last_error")),
                last_ok_at=_parse_dt(data.get("last_ok_at")),
                breaker_sessionid_hash=_opt_text(data.get("breaker_sessionid_hash")),
            )
            self._budget.restore(budget)  # validates fully before assigning
        except FileNotFoundError:
            return
        except (OSError, ValueError, TypeError):
            logger.warning("unreadable %s — starting with clean guard state", self._path)
            return
        self._state = state

    def _save(self) -> None:
        """Atomically persist the state (caller holds _state_lock). Best-effort:
        a failed write keeps working from memory rather than breaking IG calls."""
        st = self._state
        data = {
            "breaker_failures": st.breaker_failures,
            "breaker_until": _iso(st.breaker_until),
            "breaker_kind": st.breaker_kind,
            "breaker_error": st.breaker_error,
            "cooldown_until": _iso(st.cooldown_until),
            "cooldown_reason": st.cooldown_reason,
            "last_error": st.last_error,
            "last_ok_at": _iso(st.last_ok_at),
            "breaker_sessionid_hash": st.breaker_sessionid_hash,
            "budget": self._budget.counters(),
        }
        tmp = self._path.with_name(self._path.name + ".tmp")
        try:
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            os.replace(tmp, self._path)
        except OSError:
            logger.warning("could not save %s", self._path, exc_info=True)


def _sessionid_hash(sessionid: str) -> str:
    return hashlib.sha256(sessionid.strip().encode("utf-8")).hexdigest()


def _iso(when: datetime | None) -> str | None:
    return when.isoformat() if when is not None else None


def _parse_dt(value: Any) -> datetime | None:
    """A saved ISO timestamp (or null). Anything else raises ValueError."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"not a timestamp: {value!r}")
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _opt_text(value: Any) -> str | None:
    if value is None or isinstance(value, str):
        return value
    raise ValueError(f"not a text: {value!r}")


_guards: dict[str, IgGuard] = {}
_guards_lock = threading.Lock()


def get_guard(settings: Settings) -> IgGuard:
    """The process-wide guard for this state file (one lock, one budget)."""
    key = str(Path(settings.ig_guard_file).resolve())
    with _guards_lock:
        guard = _guards.get(key)
        if guard is None:
            guard = _guards[key] = IgGuard(settings)
        return guard
