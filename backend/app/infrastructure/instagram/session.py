"""Builds a configured instagrapi Client for the adapter's login (login.py).

Centralizes the anti-block hygiene (stable proxy, consistent country/locale,
saved-session reuse, and the IgGuard rails: one operation at a time, budget,
cooldown, human pacing) so every client behaves identically.
instagrapi is imported lazily to keep it optional at import time.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.infrastructure.config.settings import Settings
from app.infrastructure.instagram.error_mapping import classify_login_error
from app.infrastructure.instagram.guard import get_guard

if TYPE_CHECKING:
    from instagrapi import Client

logger = logging.getLogger(__name__)

ChallengeHandler = Callable[[str, Any], str]

_RELOGIN_FAILURE_ATTR = "_rgb_relogin_failure"


def remember_relogin_failure(client: Any, error: Exception) -> None:
    """Record a failed relogin on the client so the adapter can surface it."""
    setattr(client, _RELOGIN_FAILURE_ATTR, error)


def take_relogin_failure(client: Any) -> Exception | None:
    """Return and clear the relogin failure recorded on the client, if any."""
    error = getattr(client, _RELOGIN_FAILURE_ATTR, None)
    if error is not None:
        setattr(client, _RELOGIN_FAILURE_ATTR, None)
    return error


def build_client(settings: Settings, challenge_handler: ChallengeHandler) -> Client:
    """Return a configured (but NOT yet logged-in) instagrapi Client.

    Loads a saved session if present so we reuse device identifiers instead of
    logging in from scratch every run — the single biggest factor in avoiding
    challenges.
    """
    from instagrapi import Client

    client = Client()
    client.challenge_code_handler = challenge_handler
    # Resilience hook (instagrapi best-practice): self-heal a dead session with a
    # device-preserving relogin; re-raise throttle/feedback so callers back off.
    client.handle_exception = _make_handle_exception(settings)

    if settings.ig_proxy:
        client.set_proxy(settings.ig_proxy)
        logger.info("using proxy for Instagram requests")
    # Consistent identity (country/locale/timezone) makes the account look like a
    # stable phone in one region — a strong trust signal. Defaults target AR.
    if settings.ig_locale:
        client.set_locale(settings.ig_locale)
    if settings.ig_country:
        client.set_country(settings.ig_country)
    with contextlib.suppress(Exception):
        client.set_timezone_offset(settings.ig_timezone_offset)

    # Always load a saved session if present: it carries the device identifiers
    # (UUIDs) that keep us looking like the same phone across restarts — the
    # single biggest factor in avoiding challenges. A stale cookie here is safe:
    # the adapter validates the loaded session and falls back to sessionid or
    # user/pass if it's dead (see IgLogin.client_or_login).
    session_path = Path(settings.ig_session_file)
    if session_path.exists():
        with contextlib.suppress(Exception):  # a corrupt file must not block login
            client.load_settings(session_path)
            logger.info("loaded IG session (device+cookies) from %s", session_path)

    # No silent transport-level retries (they re-send a 429 behind our back); the
    # guard decides when Instagram may be asked again.
    client.set_retry_config(session_retry_total=0)
    # Every HTTP request now goes through the guard: budget, cooldown, pacing
    # (replaces instagrapi's own uniform delay_range) and the process-wide lock.
    get_guard(settings).install(client)
    return client


def _make_handle_exception(settings: Settings) -> Callable[[Client, Exception], None]:
    """Build instagrapi's `handle_exception` hook.

    The docs' #1 resilience pattern: on a dead session (`LoginRequired`) do a
    single device-preserving `relogin()` (reuses the same UUIDs; capped by
    instagrapi's `ReloginAttemptExceeded`, so it can't tight-loop). Every other
    error — throttle, feedback_required, challenge — is re-raised so the caller
    backs off or stops. We only relogin when user/pass exist; a sessionid-only
    client can't relogin, so we let the adapter's fallback handle it.
    """

    def handle_exception(client: Client, exc: Exception) -> None:
        from instagrapi.exceptions import LoginRequired

        if isinstance(exc, LoginRequired) and settings.has_password_login:
            logger.info("session expired mid-request — relogin (device preserved)")
            try:
                client.relogin()
            except Exception as relogin_exc:
                # A failed relogin (incl. instagrapi crashes like int(None) when IG
                # omits the password key) becomes a clear session error. It is also
                # recorded on the client: instagrapi's media_info swallows it and
                # falls back to the public endpoint, so the adapter reads it back.
                logger.warning("relogin failed: %r", relogin_exc)
                domain = classify_login_error(relogin_exc)
                remember_relogin_failure(client, domain)
                raise domain from relogin_exc
            return
        raise exc

    return handle_exception
