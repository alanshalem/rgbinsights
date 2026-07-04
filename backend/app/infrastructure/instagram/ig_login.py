"""In-app Instagram login: open a *headed* Chrome so a human logs in, then hand
the (now authenticated) profile back to the headless scraping browser.

Instagram's login page walls automated browsers, so the login itself must be a
plain, human-driven Chrome. Because Chrome locks the profile dir, we first shut
the headless scraping browser down, open a headed Chrome on the same profile,
and once `ds_user_id` appears (login done) we close it — the next Instagram op
rebuilds the headless browser on the freshly authenticated session.
"""

from __future__ import annotations

import contextlib
import logging
import time
from typing import Any

from app.infrastructure.config.settings import Settings
from app.infrastructure.instagram.chrome_cdp import (
    cdp_url,
    find_chrome,
    is_cdp_up,
    launch_chrome,
    wait_for_cdp,
)
from app.infrastructure.instagram.shared import reset_shared_source

logger = logging.getLogger(__name__)

LOGIN_URL = "https://www.instagram.com/accounts/login/"

_proc: Any = None  # the headed Chrome process while a login is open


def in_progress() -> bool:
    return _proc is not None and _proc.poll() is None


def start(settings: Settings) -> None:
    """Open the headed login window. Frees the headless browser first."""
    global _proc
    if in_progress():
        return
    reset_shared_source()  # release the locked profile
    port = settings.ig_cdp_port
    _wait_port_free(port, 15)
    chrome = find_chrome(settings.ig_chrome_path)  # may raise FileNotFoundError
    logger.info("opening headed Chrome for Instagram login")
    _proc = launch_chrome(
        chrome, settings.ig_browser_dir, port, headless=False, start_url=LOGIN_URL
    )
    wait_for_cdp(port)


def finish(settings: Settings) -> str | None:
    """Return the logged-in account pk if login is complete, else None.

    On success it closes the headed window so the scraping browser can reclaim
    the profile.
    """
    port = settings.ig_cdp_port
    if not is_cdp_up(port):
        return None
    pk = _read_pk(port)
    if pk:
        _terminate(settings)
    return pk


def cancel(settings: Settings) -> None:
    _terminate(settings)


# -- internals -------------------------------------------------------------


def _read_pk(port: int) -> str | None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(cdp_url(port))
        try:
            context = browser.contexts[0] if browser.contexts else None
            cookies = context.cookies() if context else []
        finally:
            browser.close()
    for cookie in cookies:
        if cookie.get("name") == "ds_user_id" and cookie.get("value"):
            return str(cookie["value"])
    return None


def _terminate(settings: Settings) -> None:
    global _proc
    if _proc is not None:
        with contextlib.suppress(Exception):
            _proc.terminate()
        _proc = None
    _wait_port_free(settings.ig_cdp_port, 15)


def _wait_port_free(port: int, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while is_cdp_up(port) and time.monotonic() < deadline:
        time.sleep(0.4)
