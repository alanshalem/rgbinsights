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
import json
import logging
import time
from pathlib import Path
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

# Where the login's cookies are stashed so the headless browser can re-seed from
# them on every startup — the human logs in ONCE and it survives app restarts
# (until Instagram expires the session). Holds the sessionid: keep it local and
# git-ignored (see .gitignore), same sensitivity as IG_SESSIONID in .env.
COOKIE_STORE = Path("ig_cookies.json")

_proc: Any = None  # the headed Chrome process while a login is open


def in_progress() -> bool:
    return _proc is not None and _proc.poll() is None


def save_cookies(cookies: list[dict[str, Any]]) -> None:
    with contextlib.suppress(Exception):
        COOKIE_STORE.write_text(json.dumps(cookies), encoding="utf-8")


def load_saved_cookies() -> list[dict[str, Any]] | None:
    """Cookies from the last successful login, or None if never logged in."""
    with contextlib.suppress(Exception):
        if COOKIE_STORE.exists():
            data = json.loads(COOKIE_STORE.read_text(encoding="utf-8"))
            if isinstance(data, list) and data:
                return data
    return None


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

    On success it saves the live session cookies (so the headless browser re-seeds
    from them), then closes the headed window so the scraper can reclaim the profile.
    """
    port = settings.ig_cdp_port
    if not is_cdp_up(port):
        return None
    cookies = _read_cookies(port)
    names = {str(c.get("name")): str(c.get("value", "")) for c in cookies}
    # Require a REAL login: sessionid (not just ds_user_id, which lingers after
    # logout). Without this the window closes before the human finishes.
    if not (names.get("sessionid") and names.get("ds_user_id")):
        return None
    save_cookies(cookies)  # persist BEFORE we kill Chrome (hard-kill may skip flush)
    _terminate(settings)
    return names["ds_user_id"]


def cancel(settings: Settings) -> None:
    _terminate(settings)


# -- internals -------------------------------------------------------------


def _read_cookies(port: int) -> list[dict[str, Any]]:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(cdp_url(port))
        try:
            context = browser.contexts[0] if browser.contexts else None
            return [dict(c) for c in context.cookies()] if context else []
        finally:
            browser.close()


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
