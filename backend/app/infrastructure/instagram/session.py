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

    if settings.ig_proxy:
        client.set_proxy(settings.ig_proxy)
        logger.info("using proxy for Instagram requests")
    if settings.ig_locale:
        client.set_locale(settings.ig_locale)
    if settings.ig_country:
        client.set_country(settings.ig_country)

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
