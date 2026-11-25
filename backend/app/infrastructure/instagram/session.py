"""Builds a configured instagrapi Client for the adapter's login (login.py).

Centralizes the anti-block hygiene (stable proxy, fixed Argentina
country/locale/timezone, saved-session reuse, and the IgGuard rails: one
operation at a time, budget, cooldown, human pacing) so every client behaves
identically.
instagrapi is imported lazily to keep it optional at import time.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.infrastructure.config.settings import (
    IG_COUNTRY,
    IG_LOCALE,
    IG_TIMEZONE_OFFSET,
    Settings,
)
from app.infrastructure.instagram.error_mapping import classify_login_error, is_session_error
from app.infrastructure.instagram.guard import get_guard

if TYPE_CHECKING:
    from instagrapi import Client

logger = logging.getLogger(__name__)

ChallengeHandler = Callable[[str, Any], str]

_SESSION_FAILURE_ATTR = "_rgb_session_failure"


def remember_session_failure(client: Any, error: Exception) -> None:
    """Record a session failure on the client so the adapter can surface it."""
    setattr(client, _SESSION_FAILURE_ATTR, error)


def take_session_failure(client: Any) -> Exception | None:
    """Return and clear the session failure recorded on the client, if any."""
    error = getattr(client, _SESSION_FAILURE_ATTR, None)
    if error is not None:
        setattr(client, _SESSION_FAILURE_ATTR, None)
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
    # No silent retries, challenge flows or relogins: every failure surfaces.
    client.handle_exception = _handle_exception

    if settings.ig_proxy:
        client.set_proxy(settings.ig_proxy)
        logger.info("using proxy for Instagram requests")
    # Consistent identity (country/locale/timezone) makes the account look like a
    # stable phone in one region — a strong trust signal. Fixed to Argentina.
    client.set_locale(IG_LOCALE)
    client.set_country(IG_COUNTRY)
    with contextlib.suppress(Exception):
        client.set_timezone_offset(IG_TIMEZONE_OFFSET)

    # Always load a saved session if present: it carries the device identifiers
    # (UUIDs) that keep us looking like the same phone across restarts — the
    # single biggest factor in avoiding challenges. A stale cookie here is safe:
    # the adapter validates the loaded session once and, if it's dead, asks for a
    # new pasted sessionid (see IgLogin.client_or_login); a paste reuses the device.
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


def _handle_exception(client: Client, exc: Exception) -> None:
    """instagrapi's `handle_exception` hook: never retry, never resolve.

    Set on purpose: without a hook instagrapi runs its challenge flow (more
    requests), and a hook that returns makes it re-send the request. There is
    no relogin either (L24: the only way in is a pasted sessionid). The error is
    re-raised as is (instagrapi handles it exactly as without credentials
    before); a session failure is also recorded on the client — instagrapi's
    media_info swallows it and falls back to the public endpoint, so the adapter
    reads it back instead of a misleading "not found".
    """
    if is_session_error(exc):
        remember_session_failure(client, classify_login_error(exc))
    raise exc
