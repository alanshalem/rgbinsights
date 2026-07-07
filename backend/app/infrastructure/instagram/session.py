"""Builds a configured instagrapi Client, shared by the API adapter and the
one-time interactive login script.

Centralizes the anti-block hygiene (stable proxy, consistent country/locale,
randomized delays, saved-session reuse) so both entry points behave identically.
instagrapi is imported lazily to keep it optional at import time.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.infrastructure.config.settings import Settings

if TYPE_CHECKING:
    from instagrapi import Client

logger = logging.getLogger(__name__)

ChallengeHandler = Callable[[str, Any], str]


def build_client(settings: Settings, challenge_handler: ChallengeHandler) -> Client:
    """Return a configured (but NOT yet logged-in) instagrapi Client.

    Loads a saved session if present so we reuse device identifiers instead of
    logging in from scratch every run — the single biggest factor in avoiding
    challenges.
    """
    from instagrapi import Client

    client = Client()
    client.delay_range = [
        settings.scan_min_delay_seconds,
        settings.scan_max_delay_seconds,
    ]
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
    # user/pass if it's dead (see InstagrapiInstagramSource._login).
    session_path = Path(settings.ig_session_file)
    if session_path.exists():
        with contextlib.suppress(Exception):  # a corrupt file must not block login
            client.load_settings(session_path)
            logger.info("loaded IG session (device+cookies) from %s", session_path)

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

        if isinstance(exc, LoginRequired) and settings.ig_username and settings.ig_password:
            logger.info("session expired mid-request — relogin (device preserved)")
            client.relogin()
            return
        raise exc

    return handle_exception
