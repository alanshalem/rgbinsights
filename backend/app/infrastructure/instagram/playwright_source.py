"""PlaywrightInstagramSource — drives a real logged-in browser.

The pure-`requests` web source can only reach `/users/*`; Instagram serves
media/comments/likers/DMs only to its in-browser SPA (dynamic tokens). So here
we run a headless Chromium with a *persistent* profile (logged in once, by
hand) and make the page itself call `fetch('/api/v1/...')`. Inside the real
origin those calls return JSON — exactly what the app fetches — with none of
the tokens to replicate.

All Playwright calls run on a single dedicated worker thread (Playwright's sync
API is thread-affine), so this is safe under FastAPI's threadpool.
"""

from __future__ import annotations

import atexit
import contextlib
import json
import logging
import queue
import random
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

from app.domain.entities import Comment, DmThread, IgUser, Post
from app.infrastructure.config.settings import Settings
from app.infrastructure.instagram.chrome_cdp import (
    cdp_url,
    find_chrome,
    is_cdp_up,
    launch_chrome,
    wait_for_cdp,
)
from app.infrastructure.instagram.errors import (
    ChallengeRequiredError,
    LoginRequiredError,
    PostNotFoundError,
    RateLimitedError,
    SendBlockedError,
)
from app.infrastructure.instagram.web_source import (
    extract_shortcode,
    parse_comments,
    parse_inbox,
    parse_likers,
    parse_media_info,
    shortcode_to_pk,
)

if TYPE_CHECKING:
    from playwright.sync_api import Page

logger = logging.getLogger(__name__)

_WEB_APP_ID = "936619743392459"
_HOME = "https://www.instagram.com/"

# Job = a function to run on the browser thread with the live Page.
_Job = Callable[["Page"], Any]


def _safe_terminate(proc: Any) -> None:
    with contextlib.suppress(Exception):  # best-effort cleanup
        proc.terminate()


class _BrowserWorker:
    """Owns the browser on one thread; other threads submit jobs and wait.

    Starts a plain Chrome (the login profile) and *attaches* over CDP — never
    launching through Playwright, so the session stays undetectable.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._queue: queue.Queue[tuple[_Job, Future[Any]] | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def submit(self, job: _Job) -> Any:
        self._ensure_started()
        fut: Future[Any] = Future()
        self._queue.put((job, fut))
        return fut.result()

    def _ensure_started(self) -> None:
        with self._lock:
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, daemon=True)
                self._thread.start()

    def _run(self) -> None:
        from playwright.sync_api import sync_playwright

        port = self._settings.ig_cdp_port
        proc = None
        # Reuse a Chrome already listening (e.g. from --reload or a prior run)
        # instead of launching a second one on the same locked profile.
        if not is_cdp_up(port):
            chrome = find_chrome(self._settings.ig_chrome_path)
            proc = launch_chrome(
                chrome,
                self._settings.ig_browser_dir,
                port,
                headless=self._settings.ig_browser_headless,
            )
            atexit.register(_safe_terminate, proc)
            wait_for_cdp(port)
        try:
            with sync_playwright() as p:
                browser = p.chromium.connect_over_cdp(cdp_url(port))
                context = browser.contexts[0] if browser.contexts else browser.new_context()
                page = context.pages[0] if context.pages else context.new_page()
                page.goto(_HOME, wait_until="domcontentloaded")
                while True:
                    item = self._queue.get()
                    if item is None:
                        break
                    job, fut = item
                    try:
                        fut.set_result(job(page))
                    except Exception as exc:  # noqa: BLE001 — relayed to caller
                        fut.set_exception(exc)
                browser.close()
        finally:
            if proc is not None:
                _safe_terminate(proc)


def _fetch_json(page: Page, path: str) -> dict[str, Any]:
    """Run fetch() inside the page (same-origin, fully authed) and return JSON."""
    result = page.evaluate(
        """async ({ path, appId }) => {
            const headers = { 'X-IG-App-ID': appId };
            // Some endpoints (e.g. likers) require the CSRF token from the cookie.
            const m = document.cookie.match(/csrftoken=([^;]+)/);
            if (m) headers['X-CSRFToken'] = m[1];
            const r = await fetch(path, { headers, credentials: 'include' });
            const body = await r.text();
            return { status: r.status, ct: r.headers.get('content-type') || '', body };
        }""",
        {"path": path, "appId": _WEB_APP_ID},
    )
    status = int(result["status"])
    ctype = str(result["ct"])
    body = str(result["body"])
    snippet = " ".join(body[:200].split())

    if status == 404:
        raise PostNotFoundError(path)
    if "json" not in ctype:
        raise LoginRequiredError(
            f"non-JSON from {path} (status {status}, ct {ctype}): {snippet}"
        )

    data: dict[str, Any] = json.loads(body)
    message = str(data.get("message", ""))
    if message == "checkpoint_required" or data.get("require_login"):
        raise ChallengeRequiredError("Instagram requested verification (checkpoint).")
    if status in (401, 403) or data.get("status") == "fail":
        raise LoginRequiredError(f"{path} -> status {status}: {snippet}")
    return data


def _path(base: str, params: dict[str, Any] | None = None) -> str:
    return f"{base}?{urlencode(params)}" if params else base


def _send_dm(page: Page, user_pk: str, text: str) -> None:
    """POST the DM from inside the page (the web app's broadcast endpoint)."""
    result = page.evaluate(
        """async ({ userPk, text, appId }) => {
            const headers = {
                'X-IG-App-ID': appId,
                'content-type': 'application/x-www-form-urlencoded',
            };
            const m = document.cookie.match(/csrftoken=([^;]+)/);
            if (m) headers['X-CSRFToken'] = m[1];
            const ctx = (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()));
            const params = new URLSearchParams();
            params.set('action', 'send_item');
            params.set('client_context', ctx);
            params.set('mutation_token', ctx);
            params.set('offline_threading_id', ctx);
            params.set('recipient_users', JSON.stringify([[userPk]]));
            params.set('text', text);
            const r = await fetch('/api/v1/direct_v2/threads/broadcast/text/', {
                method: 'POST', headers, credentials: 'include', body: params.toString(),
            });
            const body = await r.text();
            return { status: r.status, ct: r.headers.get('content-type') || '', body };
        }""",
        {"userPk": user_pk, "text": text, "appId": _WEB_APP_ID},
    )
    status = int(result["status"])
    body = str(result["body"])
    if "json" not in str(result["ct"]):
        raise SendBlockedError(f"respuesta no-JSON al enviar (status {status})")
    data = json.loads(body)
    if data.get("status") == "ok":
        return
    raise SendBlockedError(str(data.get("message") or f"status {status}"))


class PlaywrightInstagramSource:
    """InstagramSource backed by a logged-in headless browser."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._worker = _BrowserWorker(settings)
        self._request_count = 0

    def _throttle(self) -> None:
        """Randomized pause + hard cap per run — be a good citizen."""
        self._request_count += 1
        if self._request_count > self._settings.scan_max_requests:
            raise RateLimitedError(
                f"request cap reached ({self._settings.scan_max_requests}); stopping to stay safe"
            )
        time.sleep(
            random.uniform(
                self._settings.scan_min_delay_seconds,
                self._settings.scan_max_delay_seconds,
            )
        )

    def _get(self, base: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._throttle()
        data: dict[str, Any] = self._worker.submit(
            lambda page: _fetch_json(page, _path(base, params))
        )
        return data

    def send_dm(self, user_pk: str, text: str) -> None:
        self._worker.submit(lambda page: _send_dm(page, user_pk, text))

    def current_user_pk(self) -> str:
        def read_pk(page: Page) -> str:
            for cookie in page.context.cookies():
                if cookie.get("name") == "ds_user_id":
                    return str(cookie.get("value", ""))
            return ""

        pk: str = self._worker.submit(read_pk)
        if not pk:
            raise LoginRequiredError(
                "no logged-in browser session — run: python -m app.login_browser"
            )
        return pk

    def get_post(self, url: str) -> Post:
        shortcode = extract_shortcode(url)
        if shortcode is None:
            raise PostNotFoundError(url)
        media_pk = shortcode_to_pk(shortcode)
        return parse_media_info(self._get(f"/api/v1/media/{media_pk}/info/"))

    def get_recent_posts(self, limit: int) -> list[Post]:
        pk = self.current_user_pk()
        data = self._get(f"/api/v1/feed/user/{pk}/", {"count": limit})
        return [parse_media_info({"items": [item]}) for item in data.get("items") or []][:limit]

    def get_likers(self, media_pk: str) -> list[IgUser]:
        return parse_likers(self._get(f"/api/v1/media/{media_pk}/likers/"))

    def get_comments(self, media_pk: str) -> list[Comment]:
        comments: list[Comment] = []
        params: dict[str, Any] = {}
        for _ in range(10):
            data = self._get(f"/api/v1/media/{media_pk}/comments/", params or None)
            comments.extend(parse_comments(data))
            next_min_id = data.get("next_min_id")
            if not next_min_id:
                break
            params = {"min_id": next_min_id}
        return comments

    def get_dm_threads(self) -> list[DmThread]:
        our_pk = self.current_user_pk()
        threads: list[DmThread] = []
        params: dict[str, Any] = {"thread_message_limit": 20, "limit": 20}
        for _ in range(20):
            data = self._get("/api/v1/direct_v2/inbox/", params)
            threads.extend(parse_inbox(data, our_pk))
            inbox = data.get("inbox") or {}
            if not inbox.get("has_older"):
                break
            cursor = inbox.get("oldest_cursor")
            if not cursor:
                break
            params = {"thread_message_limit": 20, "limit": 20, "cursor": cursor}
        return threads
